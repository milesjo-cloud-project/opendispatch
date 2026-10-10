"""Local calendar adapter: records the event details in the API log, plus an in-memory fake for tests."""
import logging
from uuid import uuid4

from app.calendar.domain import CalendarEvent, EventGone

log = logging.getLogger("opendispatch.calendar")


class LogCalendar:
    """Writes calendar changes to the API log instead of a calendar.

    External calendar delivery is deferred. This adapter lets the local schedule and
    technician-link workflow stay usable without connecting to a calendar provider.

    It only logs the job id. Customer details and signed links should not be copied into
    process logs, which may be retained or collected elsewhere.
    """

    def create_event(self, event: CalendarEvent) -> str:
        external_id = f"log-{uuid4().hex}"
        log.info("External calendar sync deferred for job %s", event.job_id)
        return external_id

    def update_event(self, external_id: str, event: CalendarEvent) -> None:
        # No title or description: the job id is enough to find it, and says nothing.
        log.info("SCHEDULED JOB %s updated locally: job %s, %s",
                    external_id, event.job_id, event.starts_at)

    def cancel_event(self, external_id: str) -> None:
        log.info("SCHEDULED JOB %s cancelled locally", external_id)


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
