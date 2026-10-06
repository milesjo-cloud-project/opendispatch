"""The HTTP API end to end: login, permissions, the job flow, spend, and SMS alerts.

Runs against real Postgres; every test's writes are rolled back (see tx_session).
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.adapters.email import FakeEmail
from app.adapters.notifications import FakeNotifier, SmsNotifier
from app.adapters.passwords import Argon2Hasher
from app.adapters.sms import FakeSms
from app.auth.domain import MAX_FAILED_LOGINS, MAX_RESETS_PER_HOUR
from app.main import app
from app.shared.deps import get_alert_sender, get_email, get_hasher, get_session
from app.spend.service import send_pending_alerts

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
        self.email = FakeEmail()
        notifier = SmsNotifier(self.sms, self.fallback)
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_hasher] = lambda: FAST_HASHER
        app.dependency_overrides[get_email] = lambda: self.email
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
def api(tx_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "signup", "open")  # most tests make several companies; see "who may sign up"
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


@pytest.fixture
def no_ip_limits(monkeypatch):
    """For tests of the per-ACCOUNT rules: every test request comes from one address, so
    the per-address limits (tested below) would otherwise step in first."""
    from app.config import settings
    for name in ["login_failures_per_15_minutes", "signup_limit_per_hour", "reset_limit_per_hour"]:
        monkeypatch.setattr(settings, name, 1_000)


def test_account_locks_after_repeated_failures(api, no_ip_limits):
    _, user = api.signup()
    for _ in range(MAX_FAILED_LOGINS):
        api.call("POST", "/auth/login", json={"email": user["email"], "password": "wrong password!"})
    # Even the right password is refused while locked
    r = api.call("POST", "/auth/login", json={"email": user["email"], "password": PASSWORD})
    assert r.status_code == 401


def change_password(api, token, current, new="a brand new password"):
    return api.call("POST", "/me/password", token, json={"current_password": current, "new_password": new})


def test_wrong_current_passwords_count_toward_the_lockout(api):
    """A stolen login token can't be used to guess the real password."""
    token, user = api.signup()
    for _ in range(MAX_FAILED_LOGINS):
        assert change_password(api, token, "a wrong guess!!").status_code == 403
    r = change_password(api, token, PASSWORD)  # even the right one, while locked
    assert r.status_code == 429
    assert r.headers["retry-after"] == "900"
    assert "reset your password" in r.json()["detail"]
    assert login(api, user["email"], PASSWORD).status_code == 401  # the same lock as sign-in


def test_changing_password_clears_earlier_wrong_guesses(api):
    token, user = api.signup()
    for _ in range(MAX_FAILED_LOGINS - 1):
        change_password(api, token, "a wrong guess!!")
    api.ok("POST", "/me/password", token, status=204,
           json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert change_password(api, token, "a wrong guess!!").status_code == 403  # a fresh count, not locked
    api.ok("POST", "/auth/login", json={"email": user["email"], "password": NEW_PASSWORD})


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


# --- password reset

NEW_PASSWORD = "a fresh reset password"


def request_reset(api, email):
    return api.ok("POST", "/auth/password-reset/request", status=202, json={"email": email})


def reset_token_from_email(api, email):
    to, _, body = api.email.sent[-1]
    assert to == email
    return body.split("#token=", 1)[1].split()[0]


def test_reset_answers_the_same_for_unknown_emails(api):
    _, user = api.signup()
    known = request_reset(api, user["email"])
    unknown = request_reset(api, f"ghost-{uuid4()}@example.com")
    assert known == unknown
    assert len(api.email.sent) == 1  # only the real account gets mail
    assert "/reset-password#token=" in api.email.sent[0][2]


def test_reset_sets_new_password_and_logs_out_everywhere(api):
    token, user = api.signup()
    request_reset(api, user["email"].upper())  # email match ignores case
    reset = reset_token_from_email(api, user["email"])

    api.ok("POST", "/auth/password-reset/confirm", status=204,
           json={"token": reset, "new_password": NEW_PASSWORD})
    assert api.call("GET", "/me", token).status_code == 401
    old = api.call("POST", "/auth/login", json={"email": user["email"], "password": PASSWORD})
    assert old.status_code == 401
    api.ok("POST", "/auth/login", json={"email": user["email"], "password": NEW_PASSWORD})

    again = api.call("POST", "/auth/password-reset/confirm",
                     json={"token": reset, "new_password": "yet another password"})
    assert again.status_code == 400


def test_reset_rejects_bad_tokens_and_weak_passwords(api):
    _, user = api.signup()
    bogus = api.call("POST", "/auth/password-reset/confirm",
                     json={"token": "not-a-real-token", "new_password": NEW_PASSWORD})
    assert bogus.status_code == 400

    request_reset(api, user["email"])
    reset = reset_token_from_email(api, user["email"])
    weak = api.call("POST", "/auth/password-reset/confirm", json={"token": reset, "new_password": "short"})
    assert weak.status_code == 422
    # A weak attempt doesn't use up the link
    api.ok("POST", "/auth/password-reset/confirm", status=204,
           json={"token": reset, "new_password": NEW_PASSWORD})


def test_using_one_reset_link_cancels_the_others(api):
    _, user = api.signup()
    request_reset(api, user["email"])
    first = reset_token_from_email(api, user["email"])
    request_reset(api, user["email"])
    second = reset_token_from_email(api, user["email"])

    api.ok("POST", "/auth/password-reset/confirm", status=204, json={"token": second, "new_password": NEW_PASSWORD})
    r = api.call("POST", "/auth/password-reset/confirm", json={"token": first, "new_password": NEW_PASSWORD})
    assert r.status_code == 400


def test_reset_unlocks_a_locked_account(api, no_ip_limits):
    _, user = api.signup()
    for _ in range(MAX_FAILED_LOGINS):
        api.call("POST", "/auth/login", json={"email": user["email"], "password": "wrong password!"})
    request_reset(api, user["email"])
    api.ok("POST", "/auth/password-reset/confirm", status=204,
           json={"token": reset_token_from_email(api, user["email"]), "new_password": NEW_PASSWORD})
    api.ok("POST", "/auth/login", json={"email": user["email"], "password": NEW_PASSWORD})


def test_reset_requests_are_limited_per_hour(api, no_ip_limits):
    _, user = api.signup()
    for _ in range(MAX_RESETS_PER_HOUR + 2):
        request_reset(api, user["email"])  # same answer every time
    assert len(api.email.sent) == MAX_RESETS_PER_HOUR


# --- who may sign up (settings.signup)

SIGNUP_CLOSED = "This server isn't taking new sign-ups. Ask your company's owner to add you."


def new_signup(api):
    return api.call("POST", "/auth/signup",
                    json={"company_name": "X", "email": f"{uuid4()}@example.com", "password": PASSWORD})


def test_first_run_lets_only_the_first_company_sign_up(api, monkeypatch, tx_session):
    from sqlalchemy import select

    from app.config import settings
    from app.shared.models import Company
    if tx_session.scalar(select(Company.id).limit(1)) is not None:
        pytest.skip("needs a test database with no companies in it")
    monkeypatch.setattr(settings, "signup", "first-run")

    assert api.ok("GET", "/auth/signup") == {"open": True}
    owner, _ = api.signup()
    assert api.ok("GET", "/auth/signup") == {"open": False}
    r = new_signup(api)
    assert r.status_code == 403
    assert r.json()["detail"] == SIGNUP_CLOSED
    # The owner still adds their people as usual
    api.add_user(owner, "dispatcher")


def test_closed_signup_takes_nobody(api, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "signup", "closed")
    assert api.ok("GET", "/auth/signup") == {"open": False}
    assert new_signup(api).status_code == 403


def test_open_signup_takes_anyone(api):
    api.signup()
    assert api.ok("GET", "/auth/signup") == {"open": True}
    assert new_signup(api).status_code == 201


# --- per-address limits on the routes that need no login

def set_limit(monkeypatch, name, value):
    from app.config import settings
    monkeypatch.setattr(settings, name, value)


def login(api, email, password):
    return api.call("POST", "/auth/login", json={"email": email, "password": password})


def test_wrong_passwords_are_limited_per_address_across_accounts(api, monkeypatch):
    """Password spraying: one wrong guess on each of many accounts still runs out."""
    set_limit(monkeypatch, "login_failures_per_15_minutes", 3)
    _, a = api.signup()
    _, b = api.signup()
    assert [login(api, a["email"], "wrong password!").status_code for _ in range(2)] == [401, 401]
    assert login(api, b["email"], "wrong password!").status_code == 401
    r = login(api, b["email"], PASSWORD)  # refused before the password is even checked
    assert r.status_code == 429
    assert r.headers["retry-after"] == "900"
    assert "15 minutes" in r.json()["detail"]


def test_successful_sign_ins_dont_count(api, monkeypatch):
    """A whole office signing in from one address never trips the limit."""
    set_limit(monkeypatch, "login_failures_per_15_minutes", 2)
    _, user = api.signup()
    for _ in range(5):
        assert login(api, user["email"], PASSWORD).status_code == 200
    assert login(api, user["email"], "wrong password!").status_code == 401
    assert login(api, f"ghost-{uuid4()}@example.com", PASSWORD).status_code == 401  # no such account counts too
    assert login(api, user["email"], PASSWORD).status_code == 429


def test_login_limit_uses_the_address_the_trusted_proxy_saw(api, monkeypatch):
    set_limit(monkeypatch, "login_failures_per_15_minutes", 1)
    set_limit(monkeypatch, "trusted_proxy_hops", 1)
    _, user = api.signup()

    def from_(ip, password):
        return api.client.post("/auth/login", json={"email": user["email"], "password": password},
                               headers={"X-Forwarded-For": ip}).status_code

    assert from_("203.0.113.7", "wrong password!") == 401
    assert from_("203.0.113.7", PASSWORD) == 429
    assert from_("198.51.100.1", PASSWORD) == 200  # someone else behind the same proxy


def test_signups_are_limited_per_address(api, monkeypatch):
    set_limit(monkeypatch, "signup_limit_per_hour", 2)
    _, user = api.signup()
    dup = api.call("POST", "/auth/signup", json={"company_name": "X", "email": user["email"], "password": PASSWORD})
    assert dup.status_code == 409  # refused signups count too
    r = api.call("POST", "/auth/signup",
                 json={"company_name": "X", "email": f"{uuid4()}@example.com", "password": PASSWORD})
    assert r.status_code == 429
    assert r.headers["retry-after"] == "3600"


def test_reset_requests_are_limited_per_address(api, monkeypatch):
    """Across different emails, so nobody can flood many inboxes from one address."""
    set_limit(monkeypatch, "reset_limit_per_hour", 2)
    users = [api.signup()[1] for _ in range(3)]
    request_reset(api, users[0]["email"])
    request_reset(api, f"ghost-{uuid4()}@example.com")  # unknown emails count the same
    r = api.call("POST", "/auth/password-reset/request", json={"email": users[2]["email"]})
    assert r.status_code == 429
    assert len(api.email.sent) == 1


def test_phone_on_my_account(api):
    token, _ = api.signup()
    assert api.ok("PATCH", "/me", token, json={"phone": "555.123.4567"})["phone"] == "+15551234567"
    assert api.call("PATCH", "/me", token, json={"phone": "call me"}).status_code == 422
    assert api.ok("PATCH", "/me", token, json={"phone": None})["phone"] is None


# --- disabling accounts

def login_as(api, email, password=PASSWORD):
    return api.call("POST", "/auth/login", json={"email": email, "password": password})


def test_disabled_user_is_signed_out_and_cant_get_back_in(api, shop):
    tech_user = api.ok("GET", "/me", shop["tech"])
    other_device = login_as(api, tech_user["email"]).json()["token"]
    request_reset(api, tech_user["email"])
    pending_reset = reset_token_from_email(api, tech_user["email"])

    out = api.ok("POST", f"/users/{tech_user['id']}/disable", shop["owner"])
    assert out["disabled_at"] is not None
    for token in (shop["tech"], other_device):
        assert api.call("GET", "/me", token).status_code == 401
    # Same answer as a wrong password, so this doesn't reveal the account exists
    assert login_as(api, tech_user["email"]).json() == {"detail": "Invalid email or password"}
    # No reset email, and links sent before the disable are dead
    sent = len(api.email.sent)
    request_reset(api, tech_user["email"])
    assert len(api.email.sent) == sent
    r = api.call("POST", "/auth/password-reset/confirm", json={"token": pending_reset, "new_password": NEW_PASSWORD})
    assert r.status_code == 400
    # Off the schedule, but their job and its history stay
    techs = api.ok("GET", "/technicians", shop["owner"])
    assert [t["active"] for t in techs if t["id"] == shop["tech_profile"]["id"]] == [False]
    assert api.ok("GET", f"/jobs/{shop['job']['id']}", shop["owner"])["technician_id"] == shop["tech_profile"]["id"]

    back = api.ok("POST", f"/users/{tech_user['id']}/enable", shop["owner"])
    assert back["disabled_at"] is None
    assert login_as(api, tech_user["email"]).status_code == 200
    r = api.call("POST", "/auth/password-reset/confirm", json={"token": pending_reset, "new_password": NEW_PASSWORD})
    assert r.status_code == 400  # enabling doesn't bring old links back


def test_who_can_disable(api, shop):
    tech_id = api.ok("GET", "/me", shop["tech"])["id"]
    owner_id = shop["owner_user"]["id"]
    assert api.call("POST", f"/users/{tech_id}/disable", shop["dispatcher"]).status_code == 403
    assert api.call("POST", f"/users/{tech_id}/disable", shop["tech"]).status_code == 403
    assert api.call("POST", f"/users/{owner_id}/disable", shop["owner"]).status_code == 422  # not yourself
    stranger, _ = api.signup()
    assert api.call("POST", f"/users/{tech_id}/disable", stranger).status_code == 404
    assert api.call("POST", f"/users/{tech_id}/enable", stranger).status_code == 404


def test_disabled_owner_can_be_restored_by_another_owner(api, shop):
    second, second_user = api.add_user(shop["owner"], "owner")
    api.ok("POST", f"/users/{shop['owner_user']['id']}/disable", second)
    assert api.call("GET", "/me", shop["owner"]).status_code == 401
    # The disabled owner doesn't get budget alerts any more
    api.ok("PATCH", "/company", second, json={"sms_alerts_enabled": True})
    api.ok("POST", f"/jobs/{shop['job']['id']}/expenses", second, status=201, json={"amount_cents": 90_000})
    assert api.sms.sent == []  # the disabled owner is the one with the phone
    to, alert, _ = api.fallback.sent[-1]
    assert alert.level.value == "warning"
    assert [str(u.id) for u in to] == [second_user["id"]]

    api.ok("POST", f"/users/{shop['owner_user']['id']}/enable", second)
    assert login_as(api, shop["owner_user"]["email"]).status_code == 200


def test_inactive_technician_cant_take_new_jobs(api, shop):
    tech_id = shop["tech_profile"]["id"]
    api.ok("PATCH", f"/technicians/{tech_id}", shop["owner"], json={"active": False})
    r = api.call("POST", "/jobs", shop["dispatcher"],
                 json={"customer_id": shop["customer"]["id"], "title": "Leak", "technician_id": tech_id})
    assert r.status_code == 422
    other = api.ok("POST", "/jobs", shop["dispatcher"], status=201,
                   json={"customer_id": shop["customer"]["id"], "title": "Leak"})
    assert api.call("PATCH", f"/jobs/{other['id']}", shop["dispatcher"],
                    json={"technician_id": tech_id}).status_code == 422
    # Their existing job can still be edited (the web app re-sends the technician on every save)
    job = api.ok("PATCH", f"/jobs/{shop['job']['id']}", shop["dispatcher"],
                 json={"technician_id": tech_id, "scheduled_start": "2026-10-02T09:00:00+00:00"})
    assert job["technician_id"] == tech_id


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


def test_add_technician_in_one_go(api, shop):
    owner = shop["owner"]
    user = api.ok("POST", "/users", owner, status=201, json={
        "email": f"tech-{uuid4()}@example.com", "role": "technician", "password": PASSWORD,
        "phone": "(555) 222-3333", "technician": {"display_name": " Riley ", "hourly_rate_cents": 5_000}})
    tech = [t for t in api.ok("GET", "/technicians", owner) if t["user_id"] == user["id"]]
    assert [(t["display_name"], t["hourly_rate_cents"], t["phone"]) for t in tech] == [("Riley", 5_000, "+15552223333")]

    # A bad profile means no user either, so fixing it and retrying doesn't hit "email taken"
    email = f"tech-{uuid4()}@example.com"
    bad = api.call("POST", "/users", owner, json={"email": email, "role": "technician", "password": PASSWORD,
                                                  "technician": {"display_name": "   "}})
    assert bad.status_code == 422
    assert all(u["email"] != email for u in api.ok("GET", "/users", owner))


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

def test_create_job_persists_customer_and_defaults(api, shop):
    created = api.ok("POST", "/jobs", shop["dispatcher"], status=201,
                     json={"customer_id": shop["customer"]["id"], "title": "Leaking faucet"})

    assert created["customer_id"] == shop["customer"]["id"]
    assert created["customer_name"] == shop["customer"]["name"]
    assert created["title"] == "Leaking faucet"
    assert created["status"] == "requested"
    assert created["technician_id"] is None
    assert created["quoted_amount_cents"] is None
    assert api.ok("GET", f"/jobs/{created['id']}", shop["dispatcher"])["id"] == created["id"]


def test_create_job_with_new_customer_and_schedule_in_one_go(api, shop):
    office = shop["dispatcher"]
    customers_before = len(api.ok("GET", "/customers", office))
    created = api.ok("POST", "/jobs", office, status=201, json={
        "new_customer": {"name": "Pat New", "phone": "555-0199", "address": "4 Oak Ave"},
        "title": "Install disposal", "technician_id": shop["tech_profile"]["id"],
        "scheduled_start": START, "schedule": True})
    assert created["status"] == "scheduled"
    assert created["customer_name"] == "Pat New"
    assert len(api.ok("GET", "/customers", office)) == customers_before + 1
    events = api.ok("GET", f"/jobs/{created['id']}/events", office)
    assert [e["to_status"] for e in events] == ["scheduled"]


def test_create_job_is_all_or_nothing(api, shop):
    office = shop["dispatcher"]
    customers_before = len(api.ok("GET", "/customers", office))
    jobs_before = len(api.ok("GET", "/jobs", office))
    # Scheduling without a start time is refused after the customer would have been made
    r = api.call("POST", "/jobs", office, json={"new_customer": {"name": "Pat Retry"}, "title": "Leak",
                                                 "schedule": True})
    assert r.status_code == 422 and "start time" in r.json()["detail"]
    assert len(api.ok("GET", "/customers", office)) == customers_before
    assert len(api.ok("GET", "/jobs", office)) == jobs_before
    # One customer, either an existing one or a new one
    neither = api.call("POST", "/jobs", office, json={"title": "Leak"})
    both = api.call("POST", "/jobs", office, json={"title": "Leak", "customer_id": shop["customer"]["id"],
                                                   "new_customer": {"name": "Pat"}})
    assert neither.status_code == both.status_code == 422


def test_customer_tracking_link_from_scheduled_with_live_status(api, shop):
    job_id = shop["job"]["id"]
    assert api.call("POST", f"/jobs/{job_id}/tracking-link", shop["dispatcher"]).status_code == 409  # draft
    api.ok("POST", f"/jobs/{job_id}/status", shop["owner"], json={"status": "scheduled"})

    link = api.ok("POST", f"/jobs/{job_id}/tracking-link", shop["dispatcher"], status=201)
    token = link["path"].rsplit("/", 1)[1]
    current = api.ok("GET", f"/public/tracking/{token}")
    assert (current["title"], current["status"]) == ("Water heater", "scheduled")
    assert current["scheduled_start"] is not None

    # The same link follows the job as it moves
    for next_status in ["dispatched", "en_route", "in_progress", "completed", "invoiced"]:
        api.ok("POST", f"/jobs/{job_id}/status", shop["owner"], json={"status": next_status})
    assert api.ok("GET", f"/public/tracking/{token}")["status"] == "invoiced"
    assert api.call("GET", "/public/tracking/not-a-valid-link").status_code == 404


def test_no_tracking_link_for_a_cancelled_job_but_an_old_one_shows_it(api, shop):
    job_id = shop["job"]["id"]
    api.ok("POST", f"/jobs/{job_id}/status", shop["owner"], json={"status": "scheduled"})
    token = api.ok("POST", f"/jobs/{job_id}/tracking-link", shop["owner"], status=201)["path"].rsplit("/", 1)[1]
    api.ok("POST", f"/jobs/{job_id}/status", shop["owner"], json={"status": "cancelled"})
    assert api.call("POST", f"/jobs/{job_id}/tracking-link", shop["owner"]).status_code == 409
    assert api.ok("GET", f"/public/tracking/{token}")["status"] == "cancelled"


def test_job_attachments_accept_image_types_and_pdf(api, shop, tmp_path, monkeypatch):
    from app.adapters.storage import FileSystemStorage
    from app.jobs import routes as routes_jobs

    monkeypatch.setattr(routes_jobs, "_storage", FileSystemStorage(str(tmp_path)))
    path = f"/jobs/{shop['job']['id']}/attachments"
    image = api.call("POST", path, shop["tech"], files={"file": ("repair.HEIC", b"image-bytes", "image/heic")})
    pdf = api.call("POST", path, shop["tech"], files={"file": ("invoice.pdf", b"pdf-bytes", "application/pdf")})
    rejected = api.call("POST", path, shop["tech"], files={"file": ("script.js", b"alert(1)", "text/javascript")})

    assert image.status_code == pdf.status_code == 201
    assert image.json()["content_type"] == "image/heic"
    assert pdf.json()["content_type"] == "application/pdf"
    assert rejected.status_code == 415
    downloaded = api.call("GET", f"{path}/{image.json()['id']}", shop["tech"])
    assert downloaded.content == b"image-bytes"


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


def test_patch_job_follows_the_jobs_stage(api, shop):
    job_id, tech_id = shop["job"]["id"], shop["tech_profile"]["id"]
    office, tech = shop["dispatcher"], shop["tech"]

    def patch(body):
        return api.call("PATCH", f"/jobs/{job_id}", office, json=body)

    def move(who, to):
        return api.ok("POST", f"/jobs/{job_id}/status", who, json={"status": to})

    move(office, "scheduled")
    assert patch({"scheduled_start": None}).status_code == 422
    move(office, "dispatched")
    r = patch({"technician_id": None})
    assert r.status_code == 422 and "pull it back to scheduled" in r.json()["detail"]
    move(tech, "en_route")
    assert patch({"scheduled_start": "2026-10-01T11:00:00+00:00"}).status_code == 422
    # A refused edit saves nothing, even the parts that were allowed
    assert patch({"title": "Renamed", "scheduled_start": "2026-10-01T11:00:00+00:00"}).status_code == 422
    assert api.ok("GET", f"/jobs/{job_id}", office)["title"] == "Water heater"
    # What the web app sends on every save: unchanged technician and time are fine
    same = {"technician_id": tech_id, "scheduled_start": START}
    assert patch(same).status_code == 200

    move(tech, "in_progress")
    move(tech, "completed")
    assert patch({"technician_id": None}).status_code == 422
    assert patch({"quoted_amount_cents": 90_000}).status_code == 200  # still before the invoice
    move(office, "invoiced")
    assert patch({"quoted_amount_cents": 95_000}).status_code == 422
    assert patch({"description": "Warranty card left with customer"}).status_code == 200
    move(office, "paid")
    assert patch({"title": "Changed after paying"}).status_code == 422
    assert patch(same).status_code == 200


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


# --- online booking

def open_booking(api, shop) -> str:
    """Turn the shop's booking link on and return its booking id."""
    link = api.ok("POST", "/company/booking-link", shop["owner"], status=201)
    assert link["path"] == f"/book/{link['booking_id']}"
    return link["booking_id"]


def book(api, booking_id, **overrides):
    body = {"name": "Pat Jones", "title": "Leaking tap", "phone": "555-0100"} | overrides
    return api.call("POST", f"/public/book/{booking_id}", json=body)


def test_only_the_owner_controls_the_booking_link(api, shop):
    for who in ["dispatcher", "tech"]:
        assert api.call("POST", "/company/booking-link", shop[who]).status_code == 403
        assert api.call("DELETE", "/company/booking-link", shop[who]).status_code == 403
    assert api.call("POST", "/company/booking-link").status_code == 401


def test_booking_link_on_replace_off(api, shop):
    assert api.ok("GET", "/company", shop["owner"])["booking_id"] is None
    first = open_booking(api, shop)
    assert api.ok("GET", "/company", shop["owner"])["booking_id"] == first
    assert api.ok("GET", f"/public/book/{first}") == {"company_name": "Test Drain Co"}

    second = open_booking(api, shop)
    assert api.call("GET", f"/public/book/{first}").status_code == 404  # replaced
    assert book(api, first).status_code == 404

    api.ok("DELETE", "/company/booking-link", shop["owner"], status=204)
    assert api.call("GET", f"/public/book/{second}").status_code == 404
    assert book(api, second).status_code == 404


def test_public_booking_needs_no_login_and_gives_nothing_away(api, shop):
    booking_id = open_booking(api, shop)
    r = book(api, booking_id, email="pat@example.com", preferred_time="weekday mornings")
    assert r.status_code == 201, r.text
    assert r.json() == {"company_name": "Test Drain Co"}  # no ids to look anything up with

    inbox = api.ok("GET", "/booking-requests", shop["dispatcher"])
    assert [(x["name"], x["email"], x["status"]) for x in inbox] == [("Pat Jones", "pat@example.com", "new")]
    # Only a message so far: no new customer, no new job
    assert len(api.ok("GET", "/customers", shop["dispatcher"])) == 1
    assert len(api.ok("GET", "/jobs", shop["dispatcher"])) == 1


@pytest.mark.parametrize("overrides", [
    {"phone": None},                       # no way to reach them
    {"name": ""},
    {"title": "x" * 201},
    {"email": "not-an-email"},
    {"description": "x" * 5001},
])
def test_public_booking_validation(api, shop, overrides):
    assert book(api, open_booking(api, shop), **overrides).status_code == 422


def test_inbox_is_office_only(api, shop):
    book(api, open_booking(api, shop))
    request_id = api.ok("GET", "/booking-requests", shop["owner"])[0]["id"]
    assert api.call("GET", "/booking-requests", shop["tech"]).status_code == 403
    assert api.call("POST", f"/booking-requests/{request_id}/accept", shop["tech"], json={}).status_code == 403
    assert api.call("POST", f"/booking-requests/{request_id}/decline", shop["tech"]).status_code == 403
    assert api.call("GET", "/booking-requests").status_code == 401


def test_accept_makes_a_job_the_office_then_schedules(api, shop):
    book(api, open_booking(api, shop), description="Under the sink", preferred_time="mornings")
    request_id = api.ok("GET", "/booking-requests", shop["dispatcher"])[0]["id"]

    job = api.ok("POST", f"/booking-requests/{request_id}/accept", shop["dispatcher"], json={})
    assert (job["status"], job["title"], job["customer_name"]) == ("requested", "Leaking tap", "Pat Jones")
    assert job["description"] == "Under the sink\n\nPreferred time: mornings"
    assert api.ok("GET", "/booking-requests", shop["dispatcher"]) == []  # out of the inbox
    history = api.ok("GET", f"/jobs/{job['id']}/events", shop["dispatcher"])
    assert [e["note"] for e in history] == ["Booked online"]

    # From here it's an ordinary draft: give it a tech and a time, then schedule it
    api.ok("PATCH", f"/jobs/{job['id']}", shop["dispatcher"],
           json={"technician_id": shop["tech_profile"]["id"], "scheduled_start": START})
    assert api.ok("POST", f"/jobs/{job['id']}/status", shop["dispatcher"],
                  json={"status": "scheduled"})["status"] == "scheduled"


def test_accept_for_an_existing_customer(api, shop):
    book(api, open_booking(api, shop))
    request_id = api.ok("GET", "/booking-requests", shop["owner"])[0]["id"]
    job = api.ok("POST", f"/booking-requests/{request_id}/accept", shop["owner"],
                 json={"customer_id": shop["customer"]["id"]})
    assert (job["customer_id"], job["customer_name"]) == (shop["customer"]["id"], "Jane Doe")
    assert len(api.ok("GET", "/customers", shop["owner"])) == 1
    # Decided once: a second click changes nothing
    again = api.call("POST", f"/booking-requests/{request_id}/accept", shop["owner"], json={})
    assert again.status_code == 422
    assert len(api.ok("GET", "/jobs", shop["owner"])) == 2


def test_decline(api, shop):
    book(api, open_booking(api, shop))
    request_id = api.ok("GET", "/booking-requests", shop["owner"])[0]["id"]
    r = api.ok("POST", f"/booking-requests/{request_id}/decline", shop["dispatcher"])
    assert (r["status"], r["job_id"]) == ("declined", None)
    assert api.ok("GET", "/booking-requests", shop["owner"]) == []
    assert api.call("POST", f"/booking-requests/{request_id}/accept", shop["owner"], json={}).status_code == 422


def test_booking_requests_stay_inside_their_company(api, shop):
    book(api, open_booking(api, shop))
    request_id = api.ok("GET", "/booking-requests", shop["owner"])[0]["id"]
    stranger, _ = api.signup()
    assert api.ok("GET", "/booking-requests", stranger) == []
    assert api.call("POST", f"/booking-requests/{request_id}/accept", stranger, json={}).status_code == 404
    assert api.call("POST", f"/booking-requests/{request_id}/decline", stranger).status_code == 404
    # ...and the shop can't accept into the stranger's customers
    theirs = api.ok("POST", "/customers", stranger, status=201, json={"name": "Not yours"})
    r = api.call("POST", f"/booking-requests/{request_id}/accept", shop["owner"], json={"customer_id": theirs["id"]})
    assert r.status_code == 422


def test_honeypot_looks_like_success_but_saves_nothing(api, shop):
    r = book(api, open_booking(api, shop), website="http://cheap-pills.example")
    assert (r.status_code, r.json()) == (201, {"company_name": "Test Drain Co"})  # same as a real booking
    assert api.ok("GET", "/booking-requests", shop["owner"]) == []


def test_bookings_are_limited_per_ip_across_every_company(api, shop, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "booking_limit_per_hour", 3)
    ours = open_booking(api, shop)
    other_owner, _ = api.signup()
    theirs = api.ok("POST", "/company/booking-link", other_owner, status=201)["booking_id"]

    assert book(api, ours).status_code == 201
    assert book(api, theirs).status_code == 201
    assert book(api, "a-wrong-link").status_code == 404  # guesses count too
    r = book(api, ours)
    assert r.status_code == 429
    assert r.headers["retry-after"] == "3600"
    assert book(api, theirs).status_code == 429  # one spammer, every link
    assert len(api.ok("GET", "/booking-requests", shop["owner"])) == 1


def test_limit_uses_the_address_the_trusted_proxy_saw(api, shop, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "booking_limit_per_hour", 1)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    booking_id = open_booking(api, shop)
    body = {"name": "Pat", "title": "Tap", "phone": "555-0100"}

    def from_(chain):
        return api.client.post(f"/public/book/{booking_id}", json=body,
                               headers={"X-Forwarded-For": chain}).status_code

    assert from_("203.0.113.7") == 201
    assert from_("203.0.113.7") == 429
    assert from_("198.51.100.1") == 201  # a different customer behind the same proxy
    # Faking an earlier entry doesn't help: the proxy's own entry (rightmost) is used
    assert from_("10.9.9.9, 203.0.113.7") == 429


def test_job_list_query_count_doesnt_grow_with_jobs(api, shop, tx_session):
    """GET /jobs loads every job's customer in one query, not one query per job."""
    from sqlalchemy import event

    def count_queries():
        statements = []
        conn = tx_session.connection()
        listener = lambda *args: statements.append(args[2])  # noqa: E731
        event.listen(conn, "before_cursor_execute", listener)
        try:
            jobs = api.ok("GET", "/jobs", shop["dispatcher"])
        finally:
            event.remove(conn, "before_cursor_execute", listener)
        return len(jobs), len(statements)

    one_job = count_queries()
    for n in range(5):
        customer = api.ok("POST", "/customers", shop["dispatcher"], status=201, json={"name": f"Customer {n}"})
        api.ok("POST", "/jobs", shop["dispatcher"], status=201,
               json={"customer_id": customer["id"], "title": f"Job {n}"})
    six_jobs = count_queries()
    assert (one_job[0], six_jobs[0]) == (1, 6)
    assert six_jobs[1] == one_job[1]
    names = {j["customer_name"] for j in api.ok("GET", "/jobs", shop["dispatcher"])}
    assert names == {"Jane Doe"} | {f"Customer {n}" for n in range(5)}
