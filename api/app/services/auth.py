"""Use cases for accounts and login. The API calls these; the rules live in domain/auth.py.

Login tokens are random, shown to the client once, and stored only as a SHA-256 hash.
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.auth import (
    MAX_RESETS_PER_HOUR,
    AuthSession,
    PasswordResetToken,
    check_password_policy,
)
from app.domain.entities import Company, Technician, User, UserRole
from app.domain.errors import DomainRuleViolation
from app.ports.passwords import PasswordHasherPort


class InvalidCredentials(Exception):
    """Wrong email, wrong password, no password set, or locked. Deliberately one error for all."""


class EmailTaken(Exception):
    pass


class InvalidResetToken(Exception):
    """Unknown, used, or expired. One error for all, like InvalidCredentials."""


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
    if user.is_locked(now) or user.is_disabled:
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
    # Disabling revokes every session too; this is the backstop.
    if user is None or user.is_disabled:
        return None
    return user, auth_session


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
    _revoke_other_sessions(session, user, keep)
    session.flush()


def _revoke_other_sessions(session: Session, user: User, keep: AuthSession | None) -> None:
    stmt = (update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc)))
    if keep is not None:
        stmt = stmt.where(AuthSession.id != keep.id)
    session.execute(stmt)


@dataclass
class ResetRequest:
    user: User
    token: str


def request_password_reset(session: Session, *, email: str, now: datetime | None = None) -> ResetRequest | None:
    """Make a reset token for this email, or None if there's no such account or it asked too often.

    The API answers the same either way and sends the email in the background,
    so nobody can use this to find out which emails have accounts.
    Also works for someone who has never had a password.
    """
    now = now or datetime.now(timezone.utc)
    user = _find_by_email(session, email, lock=True)
    if user is None or user.is_disabled:
        return None
    recent = session.scalar(
        select(func.count()).select_from(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id,
               PasswordResetToken.created_at > now - timedelta(hours=1))
    )
    if recent >= MAX_RESETS_PER_HOUR:
        return None
    token = secrets.token_urlsafe(32)
    session.add(PasswordResetToken(user_id=user.id, company_id=user.company_id,
                                   token_hash=hash_token(token), created_at=now))
    session.flush()
    return ResetRequest(user, token)


def reset_email(link: str) -> tuple[str, str]:
    subject = "Reset your OpenDispatch password"
    body = (
        "Someone asked to reset the password for this OpenDispatch account.\n\n"
        f"To choose a new password, open this link within the next hour:\n{link}\n\n"
        "If that wasn't you, ignore this email. Your password won't change."
    )
    return subject, body


def confirm_password_reset(
    session: Session, hasher: PasswordHasherPort, *, token: str, new_password: str,
) -> None:
    """Set the new password, then log the account out everywhere and unlock it."""
    reset = session.scalars(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token))
        .with_for_update()
    ).one_or_none()
    if reset is None or not reset.is_usable():
        raise InvalidResetToken()
    user = session.get(User, reset.user_id)
    if user.is_disabled:  # a reset link can't bring back an account the owner shut off
        raise InvalidResetToken()
    check_password_policy(new_password)  # before using the token, so a weak password can retry

    now = datetime.now(timezone.utc)
    reset.use(now)
    user.password_hash = hasher.hash(new_password)
    user.record_successful_login()  # clears any lockout
    # Any other links still in someone's inbox stop working too
    _cancel_reset_links(session, user, now)
    _revoke_other_sessions(session, user, keep=None)
    session.flush()


def _cancel_reset_links(session: Session, user: User, now: datetime) -> None:
    session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )


def disable_user(session: Session, *, by: User, user: User) -> None:
    """An owner cuts off someone in their company: signs them out everywhere, cancels their
    reset links, and takes their technician profile off the schedule. Their jobs, expenses
    and history stay. The caller has already checked `by` is an owner of user's company."""
    if user.id == by.id:
        raise DomainRuleViolation("You can't disable your own account")
    # Lock the company's owners in a fixed order, so two owners disabling each other at
    # the same moment can't both succeed and leave nobody able to sign in.
    session.scalars(
        select(User).where(User.company_id == by.company_id, User.role == UserRole.OWNER)
        .order_by(User.id).with_for_update().execution_options(populate_existing=True)
    ).all()
    if by.is_disabled:
        raise DomainRuleViolation("Your account was disabled")
    session.refresh(user, with_for_update=True)

    now = datetime.now(timezone.utc)
    user.disable(now)
    _revoke_other_sessions(session, user, keep=None)
    _cancel_reset_links(session, user, now)
    session.execute(update(Technician).where(Technician.user_id == user.id).values(active=False))
    session.flush()


def enable_user(user: User) -> None:
    """Let them sign in again with their old password. Their technician profile stays
    inactive until the owner puts it back on the schedule."""
    user.enable()
    user.record_successful_login()  # a fresh start, not a lockout left over from before
