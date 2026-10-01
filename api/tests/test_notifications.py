from uuid import uuid4

import httpx
import pytest

from app.adapters.notifications.fake import FakeNotifier
from app.adapters.notifications.log import LogNotifier
from app.adapters.notifications.sms import SmsNotifier
from app.adapters.sms.fake import FakeSms
from app.adapters.sms.twilio import TwilioSms
from app.domain.budget import BudgetAlert, BudgetLevel
from app.domain.entities import Company, Job, User


@pytest.fixture
def company() -> Company:
    return Company(name="Test Drain Co", sms_alerts_enabled=True)


@pytest.fixture
def job(company) -> Job:
    return Job(company_id=company.id, customer_id=uuid4(), title="Repipe", quoted_amount_cents=100_000)


@pytest.fixture
def alert(job) -> BudgetAlert:
    return BudgetAlert(job.company_id, job.id, BudgetLevel.OVER, 100_000, 123_456)


def owner(company, phone=None) -> User:
    return User(company_id=company.id, email=f"o-{uuid4()}@example.com", role="owner", phone=phone)


def test_log_notifier_writes_alert_without_contact_details(caplog, company, job, alert):
    LogNotifier().send_budget_alert(company, [owner(company, "555-123-4567")], alert, job)
    assert "over budget" in caplog.text
    assert "$1,234.56 spent of $1,000.00 quoted" in caplog.text
    assert "@example.com" not in caplog.text
    assert "5551234567" not in caplog.text


def test_sms_goes_to_owners_with_phones(company, job, alert):
    sms, fallback = FakeSms(), FakeNotifier()
    with_phone, without = owner(company, "(555) 123-4567"), owner(company)
    SmsNotifier(sms, fallback).send_budget_alert(company, [with_phone, without], alert, job)

    assert sms.sent == [("+15551234567",
                         "OpenDispatch: job 'Repipe' is over budget ($1,234.56 spent of $1,000.00 quoted)")]
    assert fallback.sent[0][0] == [without]


def test_no_sms_when_company_has_it_off(company, job, alert):
    company.sms_alerts_enabled = False
    sms, fallback = FakeSms(), FakeNotifier()
    SmsNotifier(sms, fallback).send_budget_alert(company, [owner(company, "5551234567")], alert, job)
    assert sms.sent == []
    assert len(fallback.sent) == 1


def test_sms_failure_raises_so_alert_is_retried(company, job, alert):
    with pytest.raises(ConnectionError):
        SmsNotifier(FakeSms(fail=True), FakeNotifier()).send_budget_alert(
            company, [owner(company, "5551234567")], alert, job)


def test_twilio_posts_the_message():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(201, json={"sid": "SM123"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    TwilioSms("AC123", "secret", "+15550000000", http=client).send("+15551234567", "hi there")

    assert seen["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
    assert "To=%2B15551234567" in seen["body"] and "From=%2B15550000000" in seen["body"]
    assert "Body=hi+there" in seen["body"]
    assert seen["auth"].startswith("Basic ")


def test_twilio_error_raises():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"message": "The 'To' number is not a valid phone number."})))
    with pytest.raises(RuntimeError, match="not a valid phone number"):
        TwilioSms("AC123", "secret", "+15550000000", http=client).send("+1", "hi")
