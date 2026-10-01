"""Port: how the app tells people things. Adapters (log, SMS, later email) implement it."""

from typing import Protocol

from app.domain.budget import BudgetAlert
from app.domain.entities import Company, Job, User


class NotificationPort(Protocol):
    def send_budget_alert(self, company: Company, to: list[User], alert: BudgetAlert, job: Job) -> None:
        """Tell these owners that a job hit 80% or 100% of its quote.

        Raise if it couldn't be delivered; the alert stays unsent and is retried.
        """
        ...
