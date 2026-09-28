"""In-memory calendar for local dev and tests. Swapped for the Google adapter in Phase 2."""

from uuid import uuid4

from app.domain.entities import Job


class FakeCalendar:
    def __init__(self) -> None:
        self.events: dict[str, dict] = {}

    def create_event(self, job: Job, tech_email: str) -> str:
        event_id = str(uuid4())
        self.events[event_id] = {"job_id": str(job.id), "tech": tech_email}
        return event_id

    def update_event(self, external_id: str, job: Job) -> None:
        self.events[external_id]["job_id"] = str(job.id)

    def cancel_event(self, external_id: str) -> None:
        self.events.pop(external_id, None)
