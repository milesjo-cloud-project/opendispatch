"""The HTTP API end to end: login, permissions, the job flow, spend, and SMS alerts.

Runs against real Postgres; every test's writes are rolled back (see tx_session).
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.adapters.notifications.fake import FakeNotifier
from app.adapters.notifications.sms import SmsNotifier
from app.adapters.passwords.argon2 import Argon2Hasher
from app.adapters.sms.fake import FakeSms
from app.api.deps import get_alert_sender, get_hasher, get_session
from app.domain.auth import MAX_FAILED_LOGINS
from app.main import app
from app.services.spend import send_pending_alerts

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery"
START = "2026-10-01T09:00:00+00:00"
# Real argon2, just cheap settings so the suite stays fast.
FAST_HASHER = Argon2Hasher(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))


class Api:
    """A TestClient plus helpers. `as_(token)` sends requests as that user."""

    def __init__(self, session):
        self.client = TestClient(app)
        self.sms = FakeSms()
        self.fallback = FakeNotifier()
        notifier = SmsNotifier(self.sms, self.fallback)
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_hasher] = lambda: FAST_HASHER
        app.dependency_overrides[get_alert_sender] = lambda: (lambda: send_pending_alerts(session, notifier))

    def call(self, method, path, token=None, **kw):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.request(method, path, headers=headers, **kw)

    def ok(self, method, path, token=None, status=200, **kw):
        r = self.call(method, path, token, **kw)
        assert r.status_code == status, r.text
        return r.json() if r.content else None

    def signup(self, phone=None):
        email = f"owner-{uuid4()}@example.com"
        body = self.ok("POST", "/auth/signup", status=201,
                       json={"company_name": "Test Drain Co", "email": email, "password": PASSWORD,
                             "phone": phone})
        return body["token"], body["user"]

    def add_user(self, owner_token, role):
        email = f"{role}-{uuid4()}@example.com"
        user = self.ok("POST", "/users", owner_token, status=201,
                       json={"email": email, "role": role, "password": PASSWORD})
        token = self.ok("POST", "/auth/login", json={"email": email, "password": PASSWORD})["token"]
        return token, user


@pytest.fixture
def api(tx_session):
    yield Api(tx_session)
    app.dependency_overrides.clear()


@pytest.fixture
def shop(api):
    """A company with an owner, a dispatcher, a tech ($60/h), a customer, and a $1,000 job for the tech."""
    owner, owner_user = api.signup(phone="(555) 123-4567")
    dispatcher, _ = api.add_user(owner, "dispatcher")
    tech, tech_user = api.add_user(owner, "technician")
    tech_profile = api.ok("POST", "/technicians", owner, status=201,
                          json={"user_id": tech_user["id"], "display_name": "Sam", "hourly_rate_cents": 6_000})
    customer = api.ok("POST", "/customers", dispatcher, status=201, json={"name": "Jane Doe"})
    job = api.ok("POST", "/jobs", dispatcher, status=201,
                 json={"customer_id": customer["id"], "title": "Water heater", "technician_id": tech_profile["id"],
                       "scheduled_start": START, "quoted_amount_cents": 100_000})
    return dict(owner=owner, owner_user=owner_user, dispatcher=dispatcher, tech=tech,
                tech_profile=tech_profile, customer=customer, job=job)


# --- login

def test_signup_login_me_logout(api):
    token, user = api.signup()
    assert user["role"] == "owner"
    me = api.ok("GET", "/me", token)
    assert me["email"] == user["email"]

    again = api.ok("POST", "/auth/login", json={"email": user["email"].upper(), "password": PASSWORD})
    assert again["token"] != token

    api.ok("POST", "/auth/logout", token, status=204)
    assert api.call("GET", "/me", token).status_code == 401
    assert api.call("GET", "/me", again["token"]).status_code == 200  # other device still in


def test_protected_routes_need_a_token(api):
    for path in ["/me", "/jobs", "/company", "/users"]:
        r = api.call("GET", path)
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"
    assert api.call("GET", "/jobs", "not-a-real-token").status_code == 401


def test_wrong_password_and_unknown_email_look_the_same(api):
    _, user = api.signup()
    wrong = api.call("POST", "/auth/login", json={"email": user["email"], "password": "nope nope nope"})
    unknown = api.call("POST", "/auth/login", json={"email": "ghost@example.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid email or password"}


def test_account_locks_after_repeated_failures(api):
    _, user = api.signup()
    for _ in range(MAX_FAILED_LOGINS):
        api.call("POST", "/auth/login", json={"email": user["email"], "password": "wrong password!"})
    # Even the right password is refused while locked
    r = api.call("POST", "/auth/login", json={"email": user["email"], "password": PASSWORD})
    assert r.status_code == 401


def test_signup_rules(api):
    _, user = api.signup()
    dup = api.call("POST", "/auth/signup", json={"company_name": "X", "email": user["email"], "password": PASSWORD})
    assert dup.status_code == 409
    weak = api.call("POST", "/auth/signup",
                    json={"company_name": "X", "email": f"{uuid4()}@example.com", "password": "short"})
    assert weak.status_code == 422


def test_change_password_logs_out_other_devices(api):
    token, user = api.signup()
    other = api.ok("POST", "/auth/login", json={"email": user["email"], "password": PASSWORD})["token"]
    bad = api.call("POST", "/me/password", token,
                   json={"current_password": "not it at all", "new_password": "a brand new password"})
    assert bad.status_code == 403

    api.ok("POST", "/me/password", token, status=204,
           json={"current_password": PASSWORD, "new_password": "a brand new password"})
    assert api.call("GET", "/me", token).status_code == 200
    assert api.call("GET", "/me", other).status_code == 401
    api.ok("POST", "/auth/login", json={"email": user["email"], "password": "a brand new password"})


def test_phone_on_my_account(api):
    token, _ = api.signup()
    assert api.ok("PATCH", "/me", token, json={"phone": "555.123.4567"})["phone"] == "+15551234567"
    assert api.call("PATCH", "/me", token, json={"phone": "call me"}).status_code == 422
    assert api.ok("PATCH", "/me", token, json={"phone": None})["phone"] is None


# --- roles and companies

def test_owner_only_settings(api, shop):
    body = {"expense_approval_limit_cents": 25_000, "sms_alerts_enabled": True}
    assert api.call("PATCH", "/company", shop["dispatcher"], json=body).status_code == 403
    assert api.call("PATCH", "/company", shop["tech"], json=body).status_code == 403
    company = api.ok("PATCH", "/company", shop["owner"], json=body)
    assert company["expense_approval_limit_cents"] == 25_000
    assert company["sms_alerts_enabled"] is True
    assert api.call("POST", "/users", shop["dispatcher"],
                    json={"email": "x@example.com", "role": "owner", "password": PASSWORD}).status_code == 403


def test_pay_rates_are_owner_only(api, shop):
    by_owner = api.ok("GET", "/technicians", shop["owner"])
    by_dispatcher = api.ok("GET", "/technicians", shop["dispatcher"])
    assert by_owner[0]["hourly_rate_cents"] == 6_000
    assert by_dispatcher[0]["hourly_rate_cents"] is None
    assert api.call("GET", "/technicians", shop["tech"]).status_code == 403


def test_other_company_sees_nothing(api, shop):
    stranger, _ = api.signup()
    job_id = shop["job"]["id"]
    assert api.ok("GET", "/jobs", stranger) == []
    assert api.call("GET", f"/jobs/{job_id}", stranger).status_code == 404
    assert api.call("POST", f"/jobs/{job_id}/expenses", stranger, json={"amount_cents": 100}).status_code == 404
    # Can't attach the other company's customer to their own job either
    r = api.call("POST", "/jobs", stranger, json={"customer_id": shop["customer"]["id"], "title": "x"})
    assert r.status_code == 422


# --- jobs

def test_tech_sees_only_assigned_jobs_and_no_quote(api, shop):
    unassigned = api.ok("POST", "/jobs", shop["owner"], status=201,
                        json={"customer_id": shop["customer"]["id"], "title": "Unassigned"})
    tech_jobs = api.ok("GET", "/jobs", shop["tech"])
    assert [j["id"] for j in tech_jobs] == [shop["job"]["id"]]
    assert tech_jobs[0]["quoted_amount_cents"] is None
    assert api.call("GET", f"/jobs/{unassigned['id']}", shop["tech"]).status_code == 404
    assert api.ok("GET", f"/jobs/{shop['job']['id']}", shop["owner"])["quoted_amount_cents"] == 100_000


def test_status_flow_through_the_api(api, shop):
    job_id, tech, office = shop["job"]["id"], shop["tech"], shop["dispatcher"]

    def move(token, to):
        return api.call("POST", f"/jobs/{job_id}/status", token, json={"status": to})

    assert move(tech, "scheduled").status_code == 403  # office work
    assert move(office, "scheduled").status_code == 200
    assert move(office, "paid").status_code == 409     # illegal jump
    assert move(office, "dispatched").status_code == 200
    assert move(tech, "en_route").status_code == 200
    assert move(tech, "in_progress").status_code == 200
    assert move(tech, "cancelled").status_code == 403
    assert move(tech, "completed").status_code == 200

    events = api.ok("GET", f"/jobs/{job_id}/events", tech)
    assert [e["to_status"] for e in events] == ["scheduled", "dispatched", "en_route", "in_progress", "completed"]


def test_patch_job(api, shop):
    job_id = shop["job"]["id"]
    body = api.ok("PATCH", f"/jobs/{job_id}", shop["dispatcher"], json={"quoted_amount_cents": 150_000})
    assert body["quoted_amount_cents"] == 150_000
    assert body["technician_id"] == shop["tech_profile"]["id"]  # untouched
    cleared = api.ok("PATCH", f"/jobs/{job_id}", shop["dispatcher"], json={"technician_id": None})
    assert cleared["technician_id"] is None
    assert api.call("PATCH", f"/jobs/{job_id}", shop["tech"], json={"title": "x"}).status_code == 403


# --- spend

def test_expense_approval_flow(api, shop):
    job_id = shop["job"]["id"]
    small = api.ok("POST", f"/jobs/{job_id}/expenses", shop["tech"], status=201,
                   json={"amount_cents": 12_000, "vendor": "Ferguson"})
    assert small["status"] == "approved"
    assert small["spend"] == {"budget": None, "alert": None}  # techs don't see the budget

    big = api.ok("POST", f"/jobs/{job_id}/expenses", shop["tech"], status=201, json={"amount_cents": 60_000})
    assert big["status"] == "pending"

    assert api.call("POST", f"/expenses/{big['id']}/approve", shop["tech"], json={}).status_code == 403
    assert api.call("POST", f"/expenses/{big['id']}/approve", shop["dispatcher"], json={}).status_code == 403
    approved = api.ok("POST", f"/expenses/{big['id']}/approve", shop["owner"], json={"note": "ok"})
    assert approved["status"] == "approved"
    again = api.call("POST", f"/expenses/{big['id']}/reject", shop["owner"], json={})
    assert again.status_code == 422

    owners_own = api.ok("POST", f"/jobs/{job_id}/expenses", shop["owner"], status=201, json={"amount_cents": 1_000})
    tech_view = {e["id"] for e in api.ok("GET", f"/jobs/{job_id}/expenses", shop["tech"])}
    assert tech_view == {small["id"], big["id"]}
    assert owners_own["id"] in {e["id"] for e in api.ok("GET", f"/jobs/{job_id}/expenses", shop["owner"])}


def test_time_and_budget(api, shop):
    job_id = shop["job"]["id"]
    entry = api.ok("POST", f"/jobs/{job_id}/time", shop["tech"], status=201,
                   json={"started_at": START, "ended_at": "2026-10-01T10:30:00+00:00", "note": "Diagnosis"})
    assert entry["labor_cost_cents"] == 9_000

    assert api.call("POST", f"/jobs/{job_id}/time", shop["owner"],
                    json={"started_at": START, "ended_at": "2026-10-01T10:00:00+00:00"}).status_code == 403
    bad = api.call("POST", f"/jobs/{job_id}/time", shop["tech"],
                   json={"started_at": START, "ended_at": START})
    assert bad.status_code == 422

    assert api.call("GET", f"/jobs/{job_id}/budget", shop["tech"]).status_code == 403
    budget = api.ok("GET", f"/jobs/{job_id}/budget", shop["dispatcher"])
    assert budget["labor_cents"] == 9_000
    assert budget["remaining_cents"] == 91_000
    assert budget["level"] == "ok"
    assert len(api.ok("GET", f"/jobs/{job_id}/time", shop["tech"])) == 1


# --- alerts

def test_budget_alert_is_texted_when_sms_is_on(api, shop):
    api.ok("PATCH", "/company", shop["owner"], json={"sms_alerts_enabled": True})
    job_id = shop["job"]["id"]
    r = api.ok("POST", f"/jobs/{job_id}/expenses", shop["owner"], status=201, json={"amount_cents": 85_000})
    assert r["spend"]["alert"] == "warning"
    assert r["spend"]["budget"]["level"] == "warning"

    assert len(api.sms.sent) == 1
    to, body = api.sms.sent[0]
    assert to == "+15551234567"
    assert "has used 80% of its quote" in body and "Water heater" in body


def test_budget_alert_falls_back_when_sms_is_off(api, shop):
    job_id = shop["job"]["id"]
    api.ok("POST", f"/jobs/{job_id}/expenses", shop["owner"], status=201, json={"amount_cents": 120_000})
    assert api.sms.sent == []
    assert [alert.level.value for _, alert, _ in api.fallback.sent] == ["over"]


def test_tech_spend_alerts_the_owner_without_showing_the_tech(api, shop):
    api.ok("PATCH", "/company", shop["owner"], json={"sms_alerts_enabled": True})
    start = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
    r = api.ok("POST", f"/jobs/{shop['job']['id']}/time", shop["tech"], status=201,
               json={"started_at": start.isoformat(), "ended_at": (start + timedelta(hours=14)).isoformat()})
    assert r["spend"] == {"budget": None, "alert": None}
    assert len(api.sms.sent) == 1  # $840 of $1,000 -> warning went to the owner
