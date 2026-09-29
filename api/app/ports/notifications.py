"""Port: how the app tells people things. Adapters (log, email, SMS) implement it."""

from typing import Protocol

from app.domain.budget import BudgetAlert
from app.domain.entities import Job


class NotificationPort(Protocol):
    def send_budget_alert(self, to: list[str], alert: BudgetAlert, job: Job) -> None:
        """Tell the owners at these addresses that a job hit 80% or 100% of its quote."""
        ...
