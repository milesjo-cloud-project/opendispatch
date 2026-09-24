"""Core domain: plain Python, no framework or database imports allowed here."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4


class JobStatus(str, Enum):
    REQUESTED = "requested"
    SCHEDULED = "scheduled"
    EN_ROUTE = "en_route"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"


# Which status can move to which. Anything not listed is rejected.
ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.REQUESTED: {JobStatus.SCHEDULED, JobStatus.CANCELLED},
    JobStatus.SCHEDULED: {JobStatus.EN_ROUTE, JobStatus.CANCELLED},
    JobStatus.EN_ROUTE: {JobStatus.IN_PROGRESS, JobStatus.CANCELLED},
    JobStatus.IN_PROGRESS: {JobStatus.COMPLETED},
    JobStatus.COMPLETED: {JobStatus.APPROVED},
    JobStatus.APPROVED: {JobStatus.PAID},
    JobStatus.PAID: set(),
    JobStatus.CANCELLED: set(),
}


class InvalidTransition(Exception):
    pass


@dataclass
class Job:
    customer_name: str
    address: str
    description: str
    id: UUID = field(default_factory=uuid4)
    status: JobStatus = JobStatus.REQUESTED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def move_to(self, new_status: JobStatus) -> None:
        if new_status not in ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTransition(f"{self.status.value} -> {new_status.value} is not allowed")
        self.status = new_status
