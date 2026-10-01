"""Budget vs. actual for a job: the quoted amount against the spend recorded on it.

Budgets are tracked, not enforced: going over never blocks an expense, it raises an alert.
Pending expenses count toward spend, so the owner hears about an overrun before approving it.
Rejected expenses don't count. Labor will be added here once time tracking exists.
"""
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from .entities import Expense, ExpenseStatus, Job

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

    @property
    def spent_cents(self) -> int:
        return self.approved_cents + self.pending_cents

    @property
    def remaining_cents(self) -> int | None:
        """Negative when over budget. None when the job has no quote."""
        if self.quoted_cents is None:
            return None
        return self.quoted_cents - self.spent_cents

    @property
    def level(self) -> BudgetLevel:
        return level_for(self.quoted_cents, self.spent_cents)


def job_budget(job: Job, expenses: Iterable[Expense]) -> JobBudget:
    approved = pending = 0
    for expense in expenses:
        if expense.job_id != job.id:
            raise ValueError(f"Expense {expense.id} belongs to a different job")
        if expense.status == ExpenseStatus.APPROVED:
            approved += expense.amount_cents
        elif expense.status == ExpenseStatus.PENDING:
            pending += expense.amount_cents
    return JobBudget(job.quoted_amount_cents, approved, pending)
