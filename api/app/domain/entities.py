"""Domain entities. Plain Python dataclasses: nothing in domain/ imports SQLAlchemy.

The database mapping lives in infra/db/tables.py.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from .errors import DomainRuleViolation, IllegalTransition
from .job_status import JobStatus, can_transition


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(eq=False)
class Company:
    """A contractor business. Every other record belongs to exactly one company."""
    name: str
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)


class UserRole(str, Enum):
    OWNER = "owner"
    DISPATCHER = "dispatcher"
    TECHNICIAN = "technician"


@dataclass(eq=False)
class User:
    """Anyone who logs in: owner, dispatcher, or technician."""
    company_id: UUID
    email: str
    role: UserRole
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        # One account per address: Bob@x.com and bob@x.com are the same person.
        self.email = self.email.strip().lower()
        try:
            self.role = UserRole(self.role)
        except ValueError:
            raise DomainRuleViolation(f"Unknown role '{self.role}'") from None


@dataclass(eq=False)
class Technician:
    """The field-worker profile. Linked to the User they log in as."""
    company_id: UUID
    user_id: UUID
    display_name: str
    phone: str | None = None
    active: bool = True
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)


@dataclass(eq=False)
class Customer:
    company_id: UUID
    name: str
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)


@dataclass(eq=False)
class JobEvent:
    """One row per status change. Append-only history of a job."""
    job_id: UUID
    company_id: UUID
    from_status: JobStatus | None
    to_status: JobStatus
    actor_user_id: UUID | None = None
    note: str | None = None
    id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=_now)


@dataclass(eq=False)
class Job:
    company_id: UUID
    customer_id: UUID
    title: str
    description: str | None = None
    status: JobStatus = JobStatus.REQUESTED
    technician_id: UUID | None = None
    scheduled_start: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def transition_to(
        self,
        target: JobStatus,
        actor_user_id: UUID | None = None,
        note: str | None = None,
    ) -> JobEvent:
        """The ONLY way a job's status should change.

        Raises IllegalTransition or DomainRuleViolation and leaves the job untouched
        if the move isn't allowed. On success, returns the JobEvent the caller must save.
        """
        if not can_transition(self.status, target):
            raise IllegalTransition(self.status, target)

        if target == JobStatus.DISPATCHED and self.technician_id is None:
            raise DomainRuleViolation("A job needs a technician before it can be dispatched")
        if target == JobStatus.SCHEDULED and self.scheduled_start is None:
            raise DomainRuleViolation("A job needs a scheduled start time before it can be scheduled")

        event = JobEvent(
            job_id=self.id,
            company_id=self.company_id,
            from_status=self.status,
            to_status=target,
            actor_user_id=actor_user_id,
            note=note,
        )
        self.status = target
        return event
