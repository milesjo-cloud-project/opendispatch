"""Writes notifications to the API log. Used locally, and for anyone SMS doesn't reach."""

import logging

from app.domain.budget import BudgetAlert
from app.domain.entities import Company, Job, User

from .messages import budget_alert_text

log = logging.getLogger("opendispatch.notifications")


class LogNotifier:
    def send_budget_alert(self, company: Company, to: list[User], alert: BudgetAlert, job: Job) -> None:
        # Recipient count, not addresses: contact details don't belong in logs.
        log.warning("To %d owner(s), job %s: %s", len(to), job.id, budget_alert_text(alert, job))
