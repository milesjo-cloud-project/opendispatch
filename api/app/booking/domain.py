"""Online booking: what a customer sends through a company's public /book/<booking_id> link.

Nobody is logged in, so a request is only a message to the office. It holds the contact
details as typed and touches no customer or job. Accepting it is when the office links
it to a customer (an existing one or a new one) and a real job is created. Matching by
email automatically would let anyone attach junk to a real customer's history. And since
job history can never be deleted, spam must never become a job.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from app.shared.errors import DomainRuleViolation
from app.shared.models import Job, User


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BookingRequestStatus(str, Enum):
    NEW = "new"
    ACCEPTED = "accepted"  # became a job
    DECLINED = "declined"  # spam, a duplicate, or work the company doesn't do


@dataclass(eq=False)
class BookingRequest:
    company_id: UUID
    name: str
    title: str
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    description: str | None = None
    preferred_time: str | None = None  # free text, e.g. "weekday mornings"
    status: BookingRequestStatus = BookingRequestStatus.NEW
    job_id: UUID | None = None
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.title = self.title.strip()
        self.phone = (self.phone or "").strip() or None
        self.email = (self.email or "").strip() or None
        if not self.name:
            raise DomainRuleViolation("Please tell us your name")
        if not self.title:
            raise DomainRuleViolation("Please tell us what you need done")
        if not (self.phone or self.email):
            raise DomainRuleViolation("Please leave a phone number or email so we can reach you")

    def accept(self, job: Job, by: User) -> None:
        """Record that `job` was created from this request. Creating the job, and choosing
        its customer, is the caller's job; this checks it all belongs to one company."""
        if job.company_id != self.company_id or by.company_id != self.company_id:
            raise DomainRuleViolation("Booking request, job and user must belong to the same company")
        self._decide(BookingRequestStatus.ACCEPTED, by)
        self.job_id = job.id

    def decline(self, by: User) -> None:
        if by.company_id != self.company_id:
            raise DomainRuleViolation("Booking request and user must belong to the same company")
        self._decide(BookingRequestStatus.DECLINED, by)

    def _decide(self, outcome: BookingRequestStatus, by: User) -> None:
        if self.status != BookingRequestStatus.NEW:
            raise DomainRuleViolation(f"This request was already {self.status.value}")
        self.status = outcome
        self.decided_by_user_id = by.id
        self.decided_at = _now()
