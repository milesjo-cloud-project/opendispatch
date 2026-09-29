"""Writes notifications to the API log. The local-dev default until email/SMS adapters exist."""

import logging

from app.domain.budget import BudgetAlert, BudgetLevel
from app.domain.entities import Job

log = logging.getLogger("opendispatch.notifications")


def _dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


class LogNotifier:
    def send_budget_alert(self, to: list[str], alert: BudgetAlert, job: Job) -> None:
        what = "is over budget" if alert.level == BudgetLevel.OVER else "has used 80% of its quote"
        log.warning(
            # Recipient count, not addresses: email addresses don't belong in logs.
            "To %d owner(s): job %s '%s' %s (%s spent of %s quoted)",
            len(to), job.id, job.title, what,
            _dollars(alert.spent_cents), _dollars(alert.quoted_cents),
        )
