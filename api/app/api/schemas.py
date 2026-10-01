"""Request and response bodies. Money is always integer cents; times are ISO 8601 with a zone."""
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.budget import BudgetLevel
from app.domain.entities import ExpenseStatus, UserRole
from app.domain.job_status import JobStatus



def Email(**kw):
    return Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", **kw)


def Password(**kw):
    # Checked against the policy in domain/auth.py; the cap here just stops huge bodies.
    return Field(min_length=1, max_length=1024, **kw)


def Cents(**kw):
    return Field(ge=0, le=100_000_000_00, **kw)  # up to $100M


def Text200(**kw):
    return Field(min_length=1, max_length=200, **kw)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth

class SignupIn(BaseModel):
    company_name: str = Text200()
    email: str = Email()
    password: str = Password()
    phone: str | None = Field(default=None, max_length=32)


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Password()


class UserOut(Out):
    id: UUID
    company_id: UUID
    email: str
    role: UserRole
    phone: str | None


class MeOut(UserOut):
    technician_id: UUID | None


class TokenOut(BaseModel):
    token: str
    expires_at: datetime
    user: MeOut


class MeUpdate(BaseModel):
    phone: str | None = Field(max_length=32)


class ResetRequestIn(BaseModel):
    email: str = Field(max_length=320)


class ResetConfirmIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    new_password: str = Password()


class PasswordChangeIn(BaseModel):
    current_password: str = Password()
    new_password: str = Password()


# --- company, users, technicians, customers

class CompanyOut(Out):
    id: UUID
    name: str
    expense_approval_limit_cents: int
    sms_alerts_enabled: bool


class CompanyUpdate(BaseModel):
    name: str | None = Text200(default=None)
    expense_approval_limit_cents: int | None = Cents(default=None)
    sms_alerts_enabled: bool | None = None


class UserCreate(BaseModel):
    email: str = Email()
    role: UserRole
    password: str = Password()
    phone: str | None = Field(default=None, max_length=32)


class TechnicianCreate(BaseModel):
    user_id: UUID
    display_name: str = Text200()
    phone: str | None = Field(default=None, max_length=40)
    hourly_rate_cents: int | None = Cents(default=None)


class TechnicianUpdate(BaseModel):
    display_name: str | None = Text200(default=None)
    phone: str | None = Field(default=None, max_length=40)
    active: bool | None = None
    hourly_rate_cents: int | None = Cents(default=None)


class TechnicianOut(Out):
    id: UUID
    user_id: UUID
    display_name: str
    phone: str | None
    active: bool
    hourly_rate_cents: int | None  # owners only; None for everyone else


class CustomerCreate(BaseModel):
    name: str = Text200()
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    address: str | None = Field(default=None, max_length=2000)


class CustomerOut(Out):
    id: UUID
    name: str
    phone: str | None
    email: str | None
    address: str | None


# --- jobs

class JobCreate(BaseModel):
    customer_id: UUID
    title: str = Text200()
    description: str | None = Field(default=None, max_length=10_000)
    technician_id: UUID | None = None
    scheduled_start: datetime | None = None
    quoted_amount_cents: int | None = Cents(default=None)


class JobUpdate(BaseModel):
    """Only the fields you send are changed. Send null to clear technician, start or quote."""
    title: str | None = Text200(default=None)
    description: str | None = Field(default=None, max_length=10_000)
    technician_id: UUID | None = None
    scheduled_start: datetime | None = None
    quoted_amount_cents: int | None = Cents(default=None)


class JobOut(Out):
    id: UUID
    customer_id: UUID
    technician_id: UUID | None
    title: str
    description: str | None
    status: JobStatus
    scheduled_start: datetime | None
    quoted_amount_cents: int | None  # office only; None for techs
    created_at: datetime


class StatusChangeIn(BaseModel):
    status: JobStatus
    note: str | None = Field(default=None, max_length=2000)


class JobEventOut(Out):
    id: UUID
    from_status: JobStatus | None
    to_status: JobStatus
    actor_user_id: UUID | None
    note: str | None
    occurred_at: datetime


class BudgetOut(BaseModel):
    quoted_cents: int | None
    approved_cents: int
    pending_cents: int
    labor_cents: int
    spent_cents: int
    remaining_cents: int | None
    level: BudgetLevel


# --- spend

class ExpenseCreate(BaseModel):
    amount_cents: int = Field(gt=0, le=100_000_000_00)
    vendor: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    spent_on: date | None = None


class ExpenseOut(Out):
    id: UUID
    job_id: UUID
    submitted_by_user_id: UUID
    amount_cents: int
    vendor: str | None
    description: str | None
    spent_on: date | None
    status: ExpenseStatus
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class TimeEntryCreate(BaseModel):
    started_at: datetime
    ended_at: datetime
    note: str | None = Field(default=None, max_length=2000)


class TimeEntryOut(Out):
    id: UUID
    job_id: UUID
    technician_id: UUID
    started_at: datetime
    ended_at: datetime
    hourly_rate_cents: int
    labor_cost_cents: int
    note: str | None


class SpendOut(BaseModel):
    """What the app shows after recording spend. `budget` is office only; None for techs."""
    budget: BudgetOut | None
    alert: BudgetLevel | None
