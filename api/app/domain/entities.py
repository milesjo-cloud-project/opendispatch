"""Domain entities. Plain Python dataclasses: nothing in domain/ imports SQLAlchemy.

The database mapping lives in infra/db/tables.py.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from uuid import UUID, uuid4

from .errors import DomainRuleViolation, IllegalTransition
from .job_status import TERMINAL, JobStatus, can_transition

# Expenses above this need the owner's OK. Money is always whole cents: $500.00.
DEFAULT_EXPENSE_APPROVAL_LIMIT_CENTS = 50_000

# Longer than this is almost always a forgotten clock-out, not real work.
MAX_TIME_ENTRY = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_cents(value, what: str, *, allow_zero: bool) -> None:
    # bool is a subclass of int; True dollars is a bug, not one cent.
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainRuleViolation(f"{what} must be a whole number of cents")
    if value < 0 or (value == 0 and not allow_zero):
        raise DomainRuleViolation(f"{what} must be {'zero or more' if allow_zero else 'more than zero'}")


@dataclass(eq=False)
class Company:
    """A contractor business. Every other record belongs to exactly one company."""
    name: str
    expense_approval_limit_cents: int = DEFAULT_EXPENSE_APPROVAL_LIMIT_CENTS
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _require_cents(self.expense_approval_limit_cents, "Approval limit", allow_zero=True)


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
    # What an hour of this tech's time costs the company, for job budgets. Cents.
    hourly_rate_cents: int | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.hourly_rate_cents is not None:
            _require_cents(self.hourly_rate_cents, "Hourly rate", allow_zero=True)


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
    quoted_amount_cents: int | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.quoted_amount_cents is not None:
            _require_cents(self.quoted_amount_cents, "Quoted amount", allow_zero=True)

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

    def add_expense(
        self,
        company: Company,
        submitted_by: User,
        amount_cents: int,
        vendor: str | None = None,
        description: str | None = None,
        spent_on: date | None = None,
    ) -> "Expense":
        """The ONLY way to record spend on a job. Returns the Expense the caller must save.

        Amounts up to the company's approval limit are approved straight away;
        anything over it waits for the owner. An owner's own spend never waits on themselves.
        """
        if company.id != self.company_id or submitted_by.company_id != self.company_id:
            raise DomainRuleViolation("Expense, job and submitter must belong to the same company")
        if self.status in TERMINAL:
            raise DomainRuleViolation(f"Can't add expenses to a {self.status.value} job")
        _require_cents(amount_cents, "Expense amount", allow_zero=False)

        expense = Expense(
            company_id=self.company_id,
            job_id=self.id,
            submitted_by_user_id=submitted_by.id,
            amount_cents=amount_cents,
            vendor=vendor,
            description=description,
            spent_on=spent_on,
        )
        if amount_cents <= company.expense_approval_limit_cents or submitted_by.role == UserRole.OWNER:
            expense.status = ExpenseStatus.APPROVED
            expense.decided_at = expense.created_at  # approved automatically, so no decided_by
        return expense


    def log_time(
        self,
        technician: Technician,
        started_at: datetime,
        ended_at: datetime,
        note: str | None = None,
    ) -> "TimeEntry":
        """Record time the assigned tech spent on this job. Returns the TimeEntry the caller must save.

        The tech's current hourly rate is copied onto the entry, so a later raise
        doesn't rewrite what past jobs cost.
        """
        if technician.company_id != self.company_id:
            raise DomainRuleViolation("Technician and job must belong to the same company")
        if technician.id != self.technician_id:
            raise DomainRuleViolation("Only the technician assigned to a job can log time on it")
        if self.status in TERMINAL:
            raise DomainRuleViolation(f"Can't log time on a {self.status.value} job")
        if technician.hourly_rate_cents is None:
            raise DomainRuleViolation(f"{technician.display_name} needs an hourly rate before logging time")
        if started_at.tzinfo is None or ended_at.tzinfo is None:
            raise DomainRuleViolation("Start and end times must include a time zone")
        if ended_at <= started_at:
            raise DomainRuleViolation("End time must be after start time")
        if ended_at - started_at > MAX_TIME_ENTRY:
            raise DomainRuleViolation("A single time entry can't be longer than 24 hours")

        return TimeEntry(
            company_id=self.company_id,
            job_id=self.id,
            technician_id=technician.id,
            started_at=started_at,
            ended_at=ended_at,
            hourly_rate_cents=technician.hourly_rate_cents,
            note=note,
        )


@dataclass(eq=False)
class TimeEntry:
    """A block of a technician's time on a job. Create through Job.log_time()."""
    company_id: UUID
    job_id: UUID
    technician_id: UUID
    started_at: datetime
    ended_at: datetime
    hourly_rate_cents: int
    note: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    @property
    def labor_cost_cents(self) -> int:
        """Duration x rate, rounded to the nearest cent (half up)."""
        seconds = int((self.ended_at - self.started_at).total_seconds())
        return (seconds * self.hourly_rate_cents + 1800) // 3600


class ExpenseStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(eq=False)
class Expense:
    """Money spent on a job. Create through Job.add_expense(), decide with approve()/reject()."""
    company_id: UUID
    job_id: UUID
    submitted_by_user_id: UUID
    amount_cents: int
    vendor: str | None = None
    description: str | None = None
    spent_on: date | None = None
    status: ExpenseStatus = ExpenseStatus.PENDING
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def approve(self, approver: User, note: str | None = None) -> None:
        self._decide(ExpenseStatus.APPROVED, approver, note)

    def reject(self, approver: User, note: str | None = None) -> None:
        self._decide(ExpenseStatus.REJECTED, approver, note)

    def _decide(self, outcome: ExpenseStatus, approver: User, note: str | None) -> None:
        if self.status != ExpenseStatus.PENDING:
            raise DomainRuleViolation(f"Expense is already {self.status.value}")
        if approver.company_id != self.company_id or approver.role != UserRole.OWNER:
            raise DomainRuleViolation("Only the company's owner can approve or reject expenses")
        self.status = outcome
        self.decided_by_user_id = approver.id
        self.decided_at = _now()
        self.decision_note = note
