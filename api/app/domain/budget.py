"""Budget vs. actual for a job: the quoted amount against the spend recorded on it.

Budgets are tracked, not enforced: going over never blocks an expense, it raises an alert.
Pending expenses count toward spend, so the owner hears about an overrun before approving it.
Rejected expenses don't count. Labor (logged time x the tech's rate at the time) does.
"""
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from .entities import Expense, ExpenseStatus, Job, TimeEntry

WARNING_AT_PERCENT = 80


class BudgetLevel(str, Enum):
    NO_QUOTE = "no_quote"
    OK = "ok"
    WARNING = "warning"  # at or above 80% of the quote
    OVER = "over"        # at or above 100% of the quote


# Order matters for alerts: only moving UP this list is news.
_RANK = {BudgetLevel.NO_QUOTE: 0, BudgetLevel.OK: 0, BudgetLevel.WARNING: 1, BudgetLevel.OVER: 2}


def level_for(quoted_cents: int | None, spent_cents: int) -> BudgetLevel:
    if quoted_cents is None:
        return BudgetLevel.NO_QUOTE
    # Integer math, no floats: spent/quoted >= 80%  <=>  spent*100 >= quoted*80
    if spent_cents >= quoted_cents and spent_cents > 0:
        return BudgetLevel.OVER
    if spent_cents * 100 >= quoted_cents * WARNING_AT_PERCENT and spent_cents > 0:
        return BudgetLevel.WARNING
    return BudgetLevel.OK


def alert_for(quoted_cents: int | None, spent_before: int, spent_after: int) -> BudgetLevel | None:
    """The alert to send the owner when spend moves from spent_before to spent_after, if any.

    Returns WARNING or OVER only when the change crosses into that level, so each
    threshold alerts once instead of on every expense after it.
    """
    before = level_for(quoted_cents, spent_before)
    after = level_for(quoted_cents, spent_after)
    if _RANK[after] > _RANK[before]:
        return after
    return None


@dataclass(frozen=True)
class JobBudget:
    quoted_cents: int | None
    approved_cents: int
    pending_cents: int
    labor_cents: int = 0

    @property
    def spent_cents(self) -> int:
        return self.approved_cents + self.pending_cents + self.labor_cents

    @property
    def remaining_cents(self) -> int | None:
        """Negative when over budget. None when the job has no quote."""
        if self.quoted_cents is None:
            return None
        return self.quoted_cents - self.spent_cents

    @property
    def level(self) -> BudgetLevel:
        return level_for(self.quoted_cents, self.spent_cents)


def job_budget(
    job: Job, expenses: Iterable[Expense], time_entries: Iterable[TimeEntry] = ()
) -> JobBudget:
    approved = pending = labor = 0
    for entry in time_entries:
        if entry.job_id != job.id:
            raise ValueError(f"Time entry {entry.id} belongs to a different job")
        labor += entry.labor_cost_cents
    for expense in expenses:
        if expense.job_id != job.id:
            raise ValueError(f"Expense {expense.id} belongs to a different job")
        if expense.status == ExpenseStatus.APPROVED:
            approved += expense.amount_cents
        elif expense.status == ExpenseStatus.PENDING:
            pending += expense.amount_cents
    return JobBudget(job.quoted_amount_cents, approved, pending, labor)


@dataclass(eq=False)
class BudgetAlert:
    """A threshold a job crossed. Saved in the same transaction as the spend that caused it,
    then sent to the owner afterwards (sent_at is set once it goes out).

    One per job per level: a job warns once and goes over once, even if the quote changes later.
    """
    company_id: UUID
    job_id: UUID
    level: BudgetLevel
    quoted_cents: int
    spent_cents: int
    sent_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def check(cls, job: Job, before: JobBudget, after: JobBudget) -> "BudgetAlert | None":
        """The alert the move from `before` to `after` triggers, if any."""
        level = alert_for(job.quoted_amount_cents, before.spent_cents, after.spent_cents)
        if level is None:
            return None
        return cls(job.company_id, job.id, level, job.quoted_amount_cents, after.spent_cents)
