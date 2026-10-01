"""Texts budget alerts to owners who have a phone number, when the company has SMS alerts on.

Everyone else (SMS off, or no phone on file) goes to the fallback notifier instead.
"""
from app.domain.budget import BudgetAlert
from app.domain.entities import Company, Job, User
from app.ports.notifications import NotificationPort
from app.ports.sms import SmsPort

from .messages import budget_alert_text


class SmsNotifier:
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
