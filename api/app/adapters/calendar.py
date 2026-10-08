"""Calendar adapters (shared.ports.CalendarPort) for when there's no real provider: the
API log when Google isn't configured, and an in-memory fake for tests. The Google adapter
lives in adapters/google_calendar.py."""
import logging
from uuid import uuid4

from app.calendar.domain import CalendarEvent, EventGone

log = logging.getLogger("opendispatch.calendar")


class LogCalendar:
    """Writes calendar changes to the API log instead of a calendar.

    Used when GOOGLE_* isn't set, which is the normal local setup: the outbox still
    drains, so you can see what would have gone out.

    Locally it logs the whole event, link included, so you can click it straight out of
    `docker compose logs api`. Anywhere else it logs only that an event was dropped, for
    the same reason LogEmail holds back reset links: the body carries a signed job link,
    which is a credential, along with the customer's address and phone number. Logs get
    shipped and kept, so neither belongs in them.
    """

    def __init__(self, show_details: bool) -> None:
        self.show_details = show_details

    def create_event(self, event: CalendarEvent) -> str:
        external_id = f"log-{uuid4().hex}"
        if self.show_details:
            log.warning("CALENDAR EVENT (not sent, Google Calendar not configured)\n"
                        "%s\n%s to %s\nFor: %s\n%s",
                        event.title, event.starts_at, event.ends_at,
                        event.technician_email, event.description or "")
        else:
            log.error("Calendar event for job %s was not sent: Google Calendar isn't configured",
                      event.job_id)
        return external_id

    def update_event(self, external_id: str, event: CalendarEvent) -> None:
        # No title or description: the job id is enough to find it, and says nothing.
        log.warning("CALENDAR EVENT %s updated (not sent): job %s, %s",
                    external_id, event.job_id, event.starts_at)

    def cancel_event(self, external_id: str) -> None:
        log.warning("CALENDAR EVENT %s cancelled (not sent)", external_id)


class FakeCalendar:
    """In-memory calendar for tests. `fail` makes every call raise, for the retry tests."""

    def __init__(self, fail: bool = False, gone: bool = False) -> None:
        self.events: dict[str, CalendarEvent] = {}
        self.created: list[CalendarEvent] = []
        self.cancelled: list[str] = []
        self.fail = fail
        # Pretend somebody deleted the event at the provider, so update_event can't work.
        self.gone = gone

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("calendar provider is down")

    def create_event(self, event: CalendarEvent) -> str:
        self._check()
        external_id = str(uuid4())
        self.events[external_id] = event
        self.created.append(event)
        return external_id

    def update_event(self, external_id: str, event: CalendarEvent) -> None:
        self._check()
        if self.gone or external_id not in self.events:
            raise EventGone(external_id)
        self.events[external_id] = event

    def cancel_event(self, external_id: str) -> None:
        self._check()
        self.events.pop(external_id, None)  # already gone is success
        self.cancelled.append(external_id)
