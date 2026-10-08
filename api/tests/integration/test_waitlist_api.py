"""The waitlist over HTTP: the switch that keeps it off, the public form, and the admin list.

Runs against real Postgres; every test's writes are rolled back (see tx_session).
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import app
from app.shared.deps import get_session, get_waitlist_syncer

pytestmark = pytest.mark.integration

ADMIN_TOKEN = "test-waitlist-admin-token"


@pytest.fixture
def closed(tx_session, monkeypatch):
    """A server that isn't the one taking signups, which is the default."""
    from app.config import settings

    monkeypatch.setattr(settings, "waitlist", "closed")
    app.dependency_overrides[get_session] = lambda: tx_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def open_list(tx_session, monkeypatch):
    """The project's own server: waitlist on, admin token set, limits out of the way."""
    from app.config import settings

    monkeypatch.setattr(settings, "waitlist", "open")
    monkeypatch.setattr(settings, "waitlist_admin_token", SecretStr(ADMIN_TOKEN))
    monkeypatch.setattr(settings, "waitlist_limit_per_hour", 1000)
    app.dependency_overrides[get_session] = lambda: tx_session
    # The spreadsheet write happens in a background task, which TestClient runs for real.
    # It would open its own session outside this test's transaction, so it's a no-op here;
    # test_waitlist_outbox.py is where the writing itself is tested.
    app.dependency_overrides[get_waitlist_syncer] = lambda: (lambda: None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def an_email() -> str:
    return f"pat-{uuid4()}@example.com"


# --- off unless this server is the one taking signups

@pytest.mark.parametrize("method,path", [
    ("GET", "/public/waitlist"),
    ("POST", "/public/waitlist"),
    ("GET", "/waitlist"),
])
def test_every_route_is_404_when_the_waitlist_is_closed(closed, method, path):
    r = closed.request(method, path, json={"email": an_email()})
    assert r.status_code == 404


# --- the public form

def test_status_says_the_launch_window_and_the_spots_left(open_list):
    body = open_list.get("/public/waitlist").json()
    assert body["founding_spots"] == 100
    assert 0 <= body["spots_left"] <= 100
    assert body["launch"]  # whatever LAUNCH_LABEL says; the page prints it as-is


def test_joining_gives_a_spot_and_does_not_echo_anything_back(open_list):
    r = open_list.post("/public/waitlist", json={"email": an_email(), "name": "Pat Jones",
                                                 "plan": "perpetual", "trade": "Plumbing"})
    assert r.status_code == 201
    body = r.json()
    assert body["spot"] >= 1
    assert body["already_on_list"] is False
    # Nothing that could be used to look the signup up again, and no echo of the email.
    assert set(body) == {"spot", "is_founding", "already_on_list", "spots_left"}


def test_joining_twice_reports_the_same_spot_and_says_so(open_list):
    email = an_email()
    first = open_list.post("/public/waitlist", json={"email": email}).json()
    second = open_list.post("/public/waitlist", json={"email": email}).json()
    assert second["spot"] == first["spot"]
    assert (first["already_on_list"], second["already_on_list"]) == (False, True)


def test_a_bad_email_is_refused(open_list):
    r = open_list.post("/public/waitlist", json={"email": "not-an-email"})
    assert r.status_code == 422


def test_the_honeypot_answers_normally_and_saves_nothing(open_list):
    email = an_email()
    caught = open_list.post("/public/waitlist", json={"email": email, "website": "spam.example"})
    assert caught.status_code == 201  # a bot can't tell it was caught
    # Nothing was stored, so the same address can still join for real and be new.
    real = open_list.post("/public/waitlist", json={"email": email}).json()
    assert real["already_on_list"] is False


def test_too_many_signups_from_one_address_are_refused(open_list, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "waitlist_limit_per_hour", 2)
    for _ in range(2):
        assert open_list.post("/public/waitlist", json={"email": an_email()}).status_code == 201
    blocked = open_list.post("/public/waitlist", json={"email": an_email()})
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "3600"


# --- the admin list

def test_the_list_needs_the_admin_token(open_list):
    assert open_list.get("/waitlist").status_code == 404
    assert open_list.get("/waitlist", headers={"X-Waitlist-Token": "wrong"}).status_code == 404


def test_the_list_is_off_when_no_token_is_configured(open_list, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "waitlist_admin_token", None)
    # No token configured means nobody can read it, not everybody.
    assert open_list.get("/waitlist", headers={"X-Waitlist-Token": ""}).status_code == 404


def test_the_list_shows_the_signups_and_the_counts(open_list):
    email = an_email()
    open_list.post("/public/waitlist", json={"email": email, "company": "Whitfield", "plan": "annual"})
    response = open_list.get("/waitlist", headers={"X-Waitlist-Token": ADMIN_TOKEN})
    assert response.status_code == 200
    report = response.json()
    assert report["total"] >= 1
    assert report["by_plan"]["annual"] >= 1
    assert set(report["by_plan"]) == {"hosted_monthly", "annual", "perpetual", "self_hosted", "undecided"}
    mine = [s for s in report["signups"] if s["email"] == email]
    assert len(mine) == 1 and mine[0]["company"] == "Whitfield"


# --- the copy in the launch spreadsheet

def test_joining_queues_a_spreadsheet_row(open_list, tx_session):
    """In the signup's own transaction, so the row can't be queued for a signup that
    rolled back. The write itself happens after the response."""
    from sqlalchemy import select

    from app.db.tables import waitlist_outbox, waitlist_signups

    email = an_email()
    open_list.post("/public/waitlist", json={"email": email})
    queued = tx_session.execute(
        select(waitlist_outbox)
        .join(waitlist_signups, waitlist_signups.c.id == waitlist_outbox.c.signup_id)
        .where(waitlist_signups.c.email == email)
    ).mappings().all()
    assert len(queued) == 1
    assert queued[0]["sent_at"] is None


def test_joining_twice_queues_one_row(open_list, tx_session):
    """A repeat signup changes nothing, so there is nothing to write again."""
    from sqlalchemy import func, select

    from app.db.tables import waitlist_outbox, waitlist_signups

    email = an_email()
    open_list.post("/public/waitlist", json={"email": email})
    open_list.post("/public/waitlist", json={"email": email})
    count = tx_session.scalar(
        select(func.count()).select_from(waitlist_outbox)
        .join(waitlist_signups, waitlist_signups.c.id == waitlist_outbox.c.signup_id)
        .where(waitlist_signups.c.email == email)
    )
    assert count == 1


def test_the_honeypot_queues_nothing(open_list, tx_session):
    from sqlalchemy import func, select

    from app.db.tables import waitlist_outbox

    before = tx_session.scalar(select(func.count()).select_from(waitlist_outbox))
    open_list.post("/public/waitlist", json={"email": an_email(), "website": "spam.example"})
    assert tx_session.scalar(select(func.count()).select_from(waitlist_outbox)) == before


def test_resync_needs_the_admin_token(open_list):
    assert open_list.post("/waitlist/resync").status_code == 404
    assert open_list.post("/waitlist/resync", headers={"X-Waitlist-Token": "wrong"}).status_code == 404


def test_resync_queues_every_signup_again(open_list):
    open_list.post("/public/waitlist", json={"email": an_email()})
    r = open_list.post("/waitlist/resync", headers={"X-Waitlist-Token": ADMIN_TOKEN})
    assert r.status_code == 200
    assert r.json()["queued"] >= 1


def test_resync_is_404_when_the_waitlist_is_closed(closed):
    assert closed.post("/waitlist/resync").status_code == 404
