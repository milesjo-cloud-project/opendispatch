"""Ports: what the app needs from the outside world. Each one is an interface (a Protocol),
and adapters/ holds the code that talks to a real service (or a fake for tests).
Features depend on these, never on an adapter directly, so a provider can be swapped or turned off.
"""
from collections.abc import Mapping, Sequence
from typing import Protocol

from app.calendar.domain import CalendarEvent
from app.shared.models import Company, Job, User
from app.spend.budget import BudgetAlert


class CalendarPort(Protocol):
    """Where a scheduled job shows up for the technician. Adapters: Google Calendar,
    the API log when no provider is configured, and a fake for tests. Apple/ICS later.

    Every method must be safe to call twice. Writes go through the outbox
    (app/calendar/service.py), which retries, so a call that timed out after the
    provider had already acted will be made again.
    """

    def create_event(self, event: CalendarEvent) -> str:
        """Put the event on the technician's calendar and return the provider's id for it."""
        ...

    def update_event(self, external_id: str, event: CalendarEvent) -> None:
        """Make the existing event match `event`.

        Raise calendar.domain.EventGone if the provider no longer has it, so the sync
        creates a new one instead of retrying something that can't succeed.
        """
        ...

    def cancel_event(self, external_id: str) -> None:
        """Take the event off the calendar. An event that's already gone is success."""
        ...


class EmailPort(Protocol):
    """Adapters: SMTP (any provider), the log, and a fake for tests."""

    def send(self, to: str, subject: str, body: str) -> None:
        """Send a plain-text email. Raise if the server refused it."""
        ...


class DatabaseHealthPort(Protocol):
    def ping(self) -> bool: ...


class NotificationPort(Protocol):
    """How the app tells people things. Adapters: log, SMS (later email)."""

    def send_budget_alert(self, company: Company, to: list[User], alert: BudgetAlert, job: Job) -> None:
        """Tell these owners that a job hit 80% or 100% of its quote.

        Raise if it couldn't be delivered; the alert stays unsent and is retried.
        """
        ...


class PasswordHasherPort(Protocol):
    """Turning passwords into hashes and checking them. Adapter: argon2."""

    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool:
        """True when the hash was made with older settings and should be redone at next login."""
        ...


class SpreadsheetPort(Protocol):
    """A spreadsheet the people who run this server read by hand. Adapters: Google Sheets,
    the API log when no spreadsheet is configured, and a fake for tests.

    Only the launch waitlist uses this, and deliberately so: a spreadsheet is the right
    place for a list two people watch before launch and the wrong place for a
    contractor's operating data, which belongs in the database the app enforces rules on.

    Writes go through the outbox (app/waitlist/sync.py), which retries, so every call must
    be safe to make twice: `rows` is keyed by row number for exactly that reason.
    """

    def write_rows(self, rows: Mapping[int, Sequence[str]]) -> None:
        """Overwrite these 1-based rows with these cells. Raise if the provider refused."""
        ...


class SmsPort(Protocol):
    """Sending a text message. Adapters: Twilio, and a fake for tests."""

    def send(self, to: str, body: str) -> None:
        """Send `body` to an E.164 number. Raise if the provider refused it."""
        ...
