"""Notification adapters (shared.ports.NotificationPort): SMS to owners, the API log for
everyone SMS doesn't reach, and a fake for tests. The wording is shared by every channel."""
import logging

from app.shared.models import Company, Job, User
from app.shared.ports import NotificationPort, SmsPort
from app.spend.budget import BudgetAlert, BudgetLevel

log = logging.getLogger("opendispatch.notifications")


def dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def budget_alert_text(alert: BudgetAlert, job: Job) -> str:
    what = "is over budget" if alert.level == BudgetLevel.OVER else "has used 80% of its quote"
    return (f"OpenDispatch: job '{job.title}' {what} "
            f"({dollars(alert.spent_cents)} spent of {dollars(alert.quoted_cents)} quoted)")


class SmsNotifier:
    """Texts budget alerts to owners who have a phone number, when the company has SMS alerts on.

    Everyone else (SMS off, or no phone on file) goes to the fallback notifier instead.
    """

    def __init__(self, sms: SmsPort, fallback: NotificationPort) -> None:
        self.sms = sms
        self.fallback = fallback

    def send_budget_alert(self, company: Company, to: list[User], alert: BudgetAlert, job: Job) -> None:
        texted = [u for u in to if company.sms_alerts_enabled and u.phone]
        rest = [u for u in to if u not in texted]
        body = budget_alert_text(alert, job)
        for user in texted:
            self.sms.send(user.phone, body)
        if rest:
            self.fallback.send_budget_alert(company, rest, alert, job)


class LogNotifier:
    """Writes notifications to the API log. Used locally, and for anyone SMS doesn't reach."""

    def send_budget_alert(self, company: Company, to: list[User], alert: BudgetAlert, job: Job) -> None:
        # Recipient count, not addresses: contact details don't belong in logs.
        log.warning("To %d owner(s), job %s: %s", len(to), job.id, budget_alert_text(alert, job))


class FakeNotifier:
    """In-memory notifier for tests. Records what would have been sent."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[list[User], BudgetAlert, Job]] = []
        self.fail = fail

    def send_budget_alert(self, company: Company, to: list[User], alert: BudgetAlert, job: Job) -> None:
        if self.fail:
            raise ConnectionError("notifier is down")
        self.sent.append((to, alert, job))
