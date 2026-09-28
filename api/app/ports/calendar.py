"""Port: what the app needs from a calendar. Adapters (Google, emailed invite, ICS) implement it."""

from typing import Protocol

from app.domain.entities import Job


class CalendarPort(Protocol):
    def create_event(self, job: Job, tech_email: str) -> str:
        """Create an event on the tech's calendar and return its external id."""
        ...

    def update_event(self, external_id: str, job: Job) -> None: ...

    def cancel_event(self, external_id: str) -> None: ...
