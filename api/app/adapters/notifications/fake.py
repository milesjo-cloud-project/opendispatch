"""In-memory notifier for tests. Records what would have been sent."""

from app.domain.budget import BudgetAlert
from app.domain.entities import Company, Job, User


class FakeNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[list[User], BudgetAlert, Job]] = []
        self.fail = fail

    def send_budget_alert(self, company: Company, to: list[User], alert: BudgetAlert, job: Job) -> None:
        if self.fail:
            raise ConnectionError("notifier is down")
        self.sent.append((to, alert, job))
