"""Use cases for accounts and login. The API calls these; the rules live in domain/auth.py.

Login tokens are random, shown to the client once, and stored only as a SHA-256 hash.
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.auth import AuthSession, check_password_policy
from app.domain.entities import Company, User, UserRole
from app.domain.errors import DomainRuleViolation
from app.ports.passwords import PasswordHasherPort


class InvalidCredentials(Exception):
    """Wrong email, wrong password, no password set, or locked. Deliberately one error for all."""


class EmailTaken(Exception):
    pass


@dataclass
class LoginResult:
    token: str
    auth_session: AuthSession
    user: User


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_dummy_hashes: dict[int, str] = {}


def _burn_time(hasher: PasswordHasherPort, password: str) -> None:
    """Check against a throwaway hash so 'no such user' takes as long as 'wrong password'.
    Otherwise response time would reveal which emails have accounts."""
    key = id(hasher)
    if key not in _dummy_hashes:
        _dummy_hashes[key] = hasher.hash(secrets.token_urlsafe(16))
    hasher.verify(_dummy_hashes[key], password)


def _find_by_email(session: Session, email: str, *, lock: bool = False) -> User | None:
    stmt = select(User).where(func.lower(User.email) == email.strip().lower())
    if lock:
        stmt = stmt.with_for_update()
    return session.scalars(stmt).one_or_none()


def _start_session(session: Session, user: User) -> LoginResult:
    token = secrets.token_urlsafe(32)
    auth_session = AuthSession(user_id=user.id, company_id=user.company_id, token_hash=hash_token(token))
    session.add(auth_session)
    session.flush()
    return LoginResult(token, auth_session, user)


def _add_user(session: Session, user: User) -> None:
    if _find_by_email(session, user.email) is not None:
        raise EmailTaken(user.email)
    try:
        with session.begin_nested():  # a race with another signup lands here, not as a 500
            session.add(user)
            session.flush()
    except IntegrityError as exc:
        if "uq_users_email_lower" in str(exc.orig):
            raise EmailTaken(user.email) from None
        raise


def signup(
    session: Session, hasher: PasswordHasherPort, *,
    company_name: str, email: str, password: str, phone: str | None = None,
) -> LoginResult:
    """Create a new company with its first owner, and log them in."""
    check_password_policy(password)
    if not company_name.strip():
        raise DomainRuleViolation("Company name can't be empty")
    company = Company(name=company_name.strip())
    owner = User(company_id=company.id, email=email, role=UserRole.OWNER, phone=phone,
                 password_hash=hasher.hash(password))
    session.add(company)
    session.flush()
    _add_user(session, owner)
    return _start_session(session, owner)


def create_user(
    session: Session, hasher: PasswordHasherPort, *,
    company_id, email: str, role: UserRole, password: str, phone: str | None = None,
) -> User:
    """An owner adds someone to their company with a starting password."""
    check_password_policy(password)
    user = User(company_id=company_id, email=email, role=role, phone=phone,
                password_hash=hasher.hash(password))
    _add_user(session, user)
    return user


def login(
    session: Session, hasher: PasswordHasherPort, *,
    email: str, password: str, now: datetime | None = None,
) -> LoginResult:
    """Raises InvalidCredentials on any failure. The caller must COMMIT even then,
    so the failed-attempt count is saved."""
    now = now or datetime.now(timezone.utc)
    user = _find_by_email(session, email, lock=True)
    if user is None or user.password_hash is None:
        _burn_time(hasher, password)
        raise InvalidCredentials()
    if user.is_locked(now):
        _burn_time(hasher, password)
        raise InvalidCredentials()
    if not hasher.verify(user.password_hash, password):
        user.record_failed_login(now)
        session.flush()
        raise InvalidCredentials()

    user.record_successful_login()
    if hasher.needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(password)
    return _start_session(session, user)


def authenticate(session: Session, token: str) -> tuple[User, AuthSession] | None:
    auth_session = session.scalars(
        select(AuthSession).where(AuthSession.token_hash == hash_token(token))
    ).one_or_none()
    if auth_session is None or not auth_session.is_active():
        return None
    user = session.get(User, auth_session.user_id)
    return (user, auth_session) if user is not None else None


def logout(auth_session: AuthSession) -> None:
    auth_session.revoke()


def change_password(
    session: Session, hasher: PasswordHasherPort, *,
    user: User, current_password: str, new_password: str, keep: AuthSession,
) -> None:
    """Also logs out every other device, in case the old password was the problem."""
    if user.password_hash is None or not hasher.verify(user.password_hash, current_password):
        raise InvalidCredentials()
    check_password_policy(new_password)
    user.password_hash = hasher.hash(new_password)
    session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.id != keep.id,
               AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    session.flush()
