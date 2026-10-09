"""FastAPI dependencies: database session, the logged-in user, and adapters."""
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.calendar import LogCalendar
from app.adapters.email import LogEmail, SmtpEmail
from app.adapters.google_calendar import GoogleCalendar, GoogleToken
from app.adapters.google_service_account import ServiceAccountToken
from app.adapters.google_sheets import SCOPE as SHEETS_SCOPE
from app.adapters.google_sheets import GoogleSheets
from app.adapters.notifications import LogNotifier, SmsNotifier
from app.adapters.passwords import Argon2Hasher
from app.adapters.sheets import LogSheet
from app.adapters.sms import TwilioSms
from app.auth import service as auth
from app.auth.domain import AuthSession
from app.calendar.service import sync_pending
from app.config import settings
from app.db.session import make_session_factory
from app.shared.access import is_office, is_owner
from app.shared.models import Technician, User
from app.shared.ports import (
    CalendarPort,
    EmailPort,
    NotificationPort,
    PasswordHasherPort,
    SpreadsheetPort,
)
from app.spend.service import send_pending_alerts
from app.waitlist.sync import sync_pending as sync_waitlist_pending


@lru_cache
def session_factory() -> sessionmaker:
    return make_session_factory()


def get_session() -> Iterator[Session]:
    """One session per request. Routes commit explicitly; anything uncommitted is rolled back."""
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()


def client_ip(request: Request) -> str:
    """The caller's address, for per-IP limits.

    Each proxy appends the address it heard from to X-Forwarded-For, so with N trusted
    proxies the real client is the Nth entry from the right. Entries further left were
    written by the client and can say anything, so they're never used.
    """
    hops = settings.trusted_proxy_hops
    if hops > 0:
        chain = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",")]
        chain = [part for part in chain if part]
        if len(chain) >= hops:
            return chain[-hops]
    return request.client.host if request.client else "unknown"


@lru_cache
def get_hasher() -> PasswordHasherPort:
    return Argon2Hasher()


@lru_cache
def get_notifier() -> NotificationPort:
    fallback = LogNotifier()
    if not settings.sms_configured:
        return fallback
    sms = TwilioSms(settings.twilio_account_sid, settings.twilio_auth_token.get_secret_value(),
                    settings.twilio_from_number)
    return SmsNotifier(sms, fallback)


@lru_cache
def get_email() -> EmailPort:
    if not settings.email_configured:
        return LogEmail(show_body=settings.is_local)
    password = settings.smtp_password.get_secret_value() if settings.smtp_password else None
    return SmtpEmail(settings.smtp_host, settings.smtp_port, settings.smtp_username, password,
                     settings.email_from)


@lru_cache
def get_calendar() -> CalendarPort:
    if not settings.google_calendar_configured:
        return LogCalendar(show_details=settings.is_local)
    token = GoogleToken(settings.google_client_id,
                        settings.google_client_secret.get_secret_value(),
                        settings.google_refresh_token.get_secret_value())
    return GoogleCalendar(token, settings.google_calendar_id)


@lru_cache
def get_sheet() -> SpreadsheetPort:
    """The launch waitlist's spreadsheet, authenticated whichever way is configured.

    A service account is preferred and checked first: its credentials don't expire, while
    a refresh token issued under a Testing-status consent screen is killed by Google after
    7 days. The adapter takes either (adapters/google_auth.AccessTokenSource).
    """
    if not settings.google_sheets_configured:
        return LogSheet(show_details=settings.is_local)
    if settings.sheets_uses_service_account:
        token = ServiceAccountToken.from_json(settings.service_account_key, SHEETS_SCOPE)
    else:
        token = GoogleToken(settings.google_client_id,
                            settings.google_client_secret.get_secret_value(),
                            settings.sheets_refresh_token)
    return GoogleSheets(token, settings.google_sheets_id, settings.google_sheets_tab)


def get_alert_sender(notifier: NotificationPort = Depends(get_notifier)) -> Callable[[], None]:
    """Runs after the response, in its own session, once the spend has committed."""
    def send() -> None:
        with session_factory()() as session:
            send_pending_alerts(session, notifier)
            session.commit()
    return send


def get_calendar_syncer(calendar: CalendarPort = Depends(get_calendar)) -> Callable[[], None]:
    """Runs after the response, in its own session, once the job edit has committed.

    This is the usual path for a calendar write. app/outbox/worker.py is what retries
    the ones that fail, so a failure here is logged and left for it.
    """
    def sync() -> None:
        with session_factory()() as session:
            sync_pending(session, calendar)
            session.commit()
    return sync


def get_waitlist_syncer(sheet: SpreadsheetPort = Depends(get_sheet)) -> Callable[[], None]:
    """Runs after the response, in its own session, once the signup has committed.

    Signing up must not wait on Google, and must not fail because of it, so the row goes
    out here and app/outbox/worker.py retries the ones that fail.
    """
    def sync() -> None:
        with session_factory()() as session:
            sync_waitlist_pending(session, sheet)
            session.commit()
    return sync


@dataclass
class Actor:
    """The person making this request."""
    user: User
    technician: Technician | None  # their field profile, if they have one
    auth_session: AuthSession


def technician_for(session: Session, user: User) -> Technician | None:
    return session.scalars(select(Technician).where(Technician.user_id == user.id)).one_or_none()


_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in",
                         headers={"WWW-Authenticate": "Bearer"})


def current_actor(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> Actor:
    if creds is None:
        raise _unauthorized()
    found = auth.authenticate(session, creds.credentials)
    if found is None:
        raise _unauthorized()
    user, auth_session = found
    return Actor(user, technician_for(session, user), auth_session)


def office_actor(actor: Actor = Depends(current_actor)) -> Actor:
    if not is_office(actor.user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owners and dispatchers only")
    return actor


def owner_actor(actor: Actor = Depends(current_actor)) -> Actor:
    if not is_owner(actor.user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owners only")
    return actor
