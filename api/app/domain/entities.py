"""Domain entities. Plain Python dataclasses: nothing in domain/ imports SQLAlchemy.

The database mapping lives in infra/db/tables.py.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from uuid import UUID, uuid4

from .auth import LOCKOUT, MAX_FAILED_LOGINS, normalize_phone
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


def _check_quote(cents: int | None) -> None:
    if cents is not None:
        _require_cents(cents, "Quoted amount", allow_zero=True)


@dataclass(eq=False)
class Company:
    """A contractor business. Every other record belongs to exactly one company."""
    name: str
    expense_approval_limit_cents: int = DEFAULT_EXPENSE_APPROVAL_LIMIT_CENTS
    # Texting budget alerts costs money per message, so it's opt-in (a paid add-on later).
    sms_alerts_enabled: bool = False
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.set_approval_limit(self.expense_approval_limit_cents)

    def set_approval_limit(self, cents: int) -> None:
        _require_cents(cents, "Approval limit", allow_zero=True)
        self.expense_approval_limit_cents = cents


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
    phone: str | None = None  # E.164, e.g. +15551234567. Where SMS alerts go.
    password_hash: str | None = None  # None = can't log in yet
    failed_logins: int = 0
    locked_until: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        # One account per address: Bob@x.com and bob@x.com are the same person.
        self.email = self.email.strip().lower()
        try:
            self.role = UserRole(self.role)
        except ValueError:
            raise DomainRuleViolation(f"Unknown role '{self.role}'") from None
        self.set_phone(self.phone)

    def set_phone(self, raw: str | None) -> None:
        self.phone = normalize_phone(raw) if raw else None

    def is_locked(self, now: datetime) -> bool:
        return self.locked_until is not None and now < self.locked_until

    def record_failed_login(self, now: datetime) -> None:
        """After MAX_FAILED_LOGINS wrong passwords in a row, lock the account for LOCKOUT."""
        self.failed_logins += 1
        if self.failed_logins >= MAX_FAILED_LOGINS:
            self.locked_until = now + LOCKOUT
            self.failed_logins = 0

    def record_successful_login(self) -> None:
        self.failed_logins = 0
        self.locked_until = None


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
        self.set_hourly_rate(self.hourly_rate_cents)

    def set_hourly_rate(self, cents: int | None) -> None:
        if cents is not None:
            _require_cents(cents, "Hourly rate", allow_zero=True)
        self.hourly_rate_cents = cents


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
class JobAttachment:
    """Metadata for a job file; file bytes live behind a storage adapter."""
    company_id: UUID
    job_id: UUID
    uploaded_by_user_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    storage_key: str
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)


_S = JobStatus

# What can still be edited at each stage. Setting a field to the value it already has is
# always fine (the web app re-sends the technician and time on every save).
# Who's doing the work can change until it's done; Dispatched and later need someone.
REASSIGNABLE = frozenset({_S.REQUESTED, _S.SCHEDULED, _S.DISPATCHED, _S.EN_ROUTE, _S.IN_PROGRESS})
UNASSIGNABLE = frozenset({_S.REQUESTED, _S.SCHEDULED})
# From en route on, the start time is what happened, not a plan.
RESCHEDULABLE = frozenset({_S.REQUESTED, _S.SCHEDULED, _S.DISPATCHED})
# The quote is what the customer was billed.
QUOTE_LOCKED = frozenset({_S.INVOICED, _S.PAID, _S.CANCELLED})


def _label(status: JobStatus) -> str:
    return status.value.replace("_", " ")


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
        _check_quote(self.quoted_amount_cents)

    # --- edits. Like transition_to(), these leave the job untouched when they refuse.

    def _require_open(self) -> None:
        if self.status in TERMINAL:
            raise DomainRuleViolation(f"A {_label(self.status)} job can't be changed")

    def rename(self, title: str) -> None:
        title = title.strip()
        if title == self.title:
            return
        self._require_open()
        if not title:
            raise DomainRuleViolation("A job needs a title")
        self.title = title

    def set_description(self, description: str | None) -> None:
        if description == self.description:
            return
        self._require_open()
        self.description = description

    def assign(self, technician_id: UUID | None) -> None:
        """Change or clear the technician. Checking the technician exists, belongs to the
        company and is active is the caller's job; this checks the job's stage."""
        if technician_id == self.technician_id:
            return
        if self.status not in REASSIGNABLE:
            raise DomainRuleViolation(f"The technician on a {_label(self.status)} job can't change")
        if technician_id is None and self.status not in UNASSIGNABLE:
            hint = "; pull it back to scheduled first" if self.status == JobStatus.DISPATCHED else ""
            raise DomainRuleViolation(f"A {_label(self.status)} job needs a technician{hint}")
        self.technician_id = technician_id

    def reschedule(self, start: datetime | None) -> None:
        if start == self.scheduled_start:
            return
        if self.status not in RESCHEDULABLE:
            raise DomainRuleViolation(f"A job that's {_label(self.status)} keeps its scheduled time")
        if start is None and self.status != JobStatus.REQUESTED:
            raise DomainRuleViolation(f"A {_label(self.status)} job needs a start time")
        self.scheduled_start = start

    def set_quote(self, cents: int | None) -> None:
        if cents == self.quoted_amount_cents and not isinstance(cents, bool):
            return
        if self.status in QUOTE_LOCKED:
            raise DomainRuleViolation(f"The quote on a {_label(self.status)} job can't change")
        _check_quote(cents)
        self.quoted_amount_cents = cents

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
