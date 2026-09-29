"""The words in a notification, shared by every channel."""

from app.domain.budget import BudgetAlert, BudgetLevel
from app.domain.entities import Job


def dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def budget_alert_text(alert: BudgetAlert, job: Job) -> str:
    what = "is over budget" if alert.level == BudgetLevel.OVER else "has used 80% of its quote"
    return (f"OpenDispatch: job '{job.title}' {what} "
            f"({dollars(alert.spent_cents)} spent of {dollars(alert.quoted_cents)} quoted)")
