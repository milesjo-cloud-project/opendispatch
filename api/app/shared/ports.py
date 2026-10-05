"""Ports: what the app needs from the outside world. Each one is an interface (a Protocol),
and adapters/ holds the code that talks to a real service (or a fake for tests).
Features depend on these, never on an adapter directly, so a provider can be swapped or turned off.
"""
from typing import Protocol

from app.shared.models import Company, Job, User
from app.spend.budget import BudgetAlert


class CalendarPort(Protocol):
    """Adapters: Google, emailed invite, ICS (Phase 2)."""

    def create_event(self, job: Job, tech_email: str) -> str:
        """Create an event on the tech's calendar and return its external id."""
        ...

    def update_event(self, external_id: str, job: Job) -> None: ...

    def cancel_event(self, external_id: str) -> None: ...


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


class SmsPort(Protocol):
    """Sending a text message. Adapters: Twilio, and a fake for tests."""

    def send(self, to: str, body: str) -> None:
        """Send `body` to an E.164 number. Raise if the provider refused it."""
        ...
