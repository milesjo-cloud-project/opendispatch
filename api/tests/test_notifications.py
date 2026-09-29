from uuid import uuid4

from app.adapters.notifications.log import LogNotifier
from app.domain.budget import BudgetAlert, BudgetLevel
from app.domain.entities import Job


def test_log_notifier_writes_alert_without_addresses(caplog):
    job = Job(company_id=uuid4(), customer_id=uuid4(), title="Repipe", quoted_amount_cents=100_000)
    alert = BudgetAlert(job.company_id, job.id, BudgetLevel.OVER, 100_000, 123_456)
    LogNotifier().send_budget_alert(["owner@example.com"], alert, job)

    assert "over budget" in caplog.text
    assert "$1,234.56 spent of $1,000.00 quoted" in caplog.text
    assert "owner@example.com" not in caplog.text
