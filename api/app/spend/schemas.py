"""Request and response bodies for expenses, logged time and job budgets."""
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.models import ExpenseStatus
from app.shared.schemas import Out
from app.spend.budget import BudgetLevel


class BudgetOut(BaseModel):
    quoted_cents: int | None
    approved_cents: int
    pending_cents: int
    labor_cents: int
    spent_cents: int
    remaining_cents: int | None
    level: BudgetLevel



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
