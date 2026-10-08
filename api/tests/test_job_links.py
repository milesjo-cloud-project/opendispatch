"""Technician job links: the signing, the expiry, and every way a token can be refused."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.jobs import links
from app.shared.models import Job

KEY = b"test-signing-key"
OTHER_KEY = b"someone-elses-key"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def a_token(*, key=KEY, expires_at=None, job_id=None, technician_id=None) -> tuple[str, dict]:
    ids = {"job_id": job_id or uuid4(), "technician_id": technician_id or uuid4()}
    token = links.mint(**ids, key=key, expires_at=expires_at or NOW + timedelta(hours=1))
    return token, ids


def test_round_trip_says_which_job_and_technician():
    token, ids = a_token()
    link = links.verify(token, key=KEY, now=NOW)
    assert (link.job_id, link.technician_id) == (ids["job_id"], ids["technician_id"])
    assert link.expires_at == NOW + timedelta(hours=1)


def test_a_token_signed_with_another_key_is_refused():
    token, _ = a_token(key=OTHER_KEY)
    with pytest.raises(links.InvalidJobLink):
        links.verify(token, key=KEY, now=NOW)


def test_editing_the_payload_is_refused():
    """The point of signing: swapping in another job's id must not work."""
    token, _ = a_token()
    payload, _, signature = token.rpartition(".")
    version, job_hex, tech_hex, expires = payload.split(".")
    tampered = f"{version}.{uuid4().hex}.{tech_hex}.{expires}.{signature}"
    with pytest.raises(links.InvalidJobLink):
        links.verify(tampered, key=KEY, now=NOW)


def test_pushing_the_expiry_out_is_refused():
    token, _ = a_token(expires_at=NOW - timedelta(hours=1))
    payload, _, signature = token.rpartition(".")
    version, job_hex, tech_hex, _expires = payload.split(".")
    later = int((NOW + timedelta(days=365)).timestamp())
    with pytest.raises(links.InvalidJobLink):
        links.verify(f"{version}.{job_hex}.{tech_hex}.{later}.{signature}", key=KEY, now=NOW)


def test_an_expired_token_is_refused_even_though_it_is_signed():
    token, _ = a_token(expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(links.InvalidJobLink):
        links.verify(token, key=KEY, now=NOW)


def test_the_moment_of_expiry_is_already_too_late():
    token, _ = a_token(expires_at=NOW)
    with pytest.raises(links.InvalidJobLink):
        links.verify(token, key=KEY, now=NOW)


@pytest.mark.parametrize("token", ["", ".", "nonsense", "1.2.3", "1..", "a" * 500])
def test_garbage_is_refused_rather_than_crashing(token):
    with pytest.raises(links.InvalidJobLink):
        links.verify(token, key=KEY, now=NOW)


@pytest.mark.parametrize("token", ["é.é.é.é", "1.a.b.c.ü", "1." + "ü" * 100, "日本.語"])
def test_a_token_with_non_ascii_is_refused_rather_than_crashing(token):
    """hmac.compare_digest raises TypeError on a str holding non-ASCII, and a URL can hold
    anything, so comparing as str turned any such link into an unauthenticated 500."""
    with pytest.raises(links.InvalidJobLink):
        links.verify(token, key=KEY, now=NOW)


def test_a_token_from_another_version_is_refused():
    """Signed by us, but a shape this code doesn't read. Better refused than guessed at."""
    payload = f"2.{uuid4().hex}.{uuid4().hex}.{int((NOW + timedelta(hours=1)).timestamp())}"
    token = f"{payload}.{links._signature(payload, KEY)}"
    with pytest.raises(links.InvalidJobLink):
        links.verify(token, key=KEY, now=NOW)


def test_a_signed_payload_that_is_not_a_token_is_refused():
    """Right key, wrong contents: the parse has to fail safely, not raise ValueError."""
    payload = f"1.not-a-uuid.{uuid4().hex}.{int(NOW.timestamp()) + 60}"
    token = f"{payload}.{links._signature(payload, KEY)}"
    with pytest.raises(links.InvalidJobLink):
        links.verify(token, key=KEY, now=NOW)


# --- how long a link lasts

def test_expiry_runs_from_the_scheduled_time_not_now():
    """A job three weeks out needs a link that still works on the day."""
    start = NOW + timedelta(days=21)
    assert links.expiry_for(start, timedelta(hours=72), NOW) == start + timedelta(hours=72)


def test_a_job_in_the_past_expires_from_now():
    """Not from its start, or a link to last month's job would already be dead."""
    assert links.expiry_for(NOW - timedelta(days=5), timedelta(hours=72), NOW) == NOW + timedelta(hours=72)


def test_a_job_with_no_time_expires_from_now():
    assert links.expiry_for(None, timedelta(hours=72), NOW) == NOW + timedelta(hours=72)


# --- minting from a job

def test_link_for_job_covers_the_job_until_after_it_starts():
    job = Job(company_id=uuid4(), customer_id=uuid4(), title="Leak",
              technician_id=uuid4(), scheduled_start=NOW + timedelta(days=2))
    path, expires_at = links.link_for_job(job, key=KEY, ttl=timedelta(hours=72), now=NOW)
    assert path.startswith("/j/")
    link = links.verify(path.removeprefix("/j/"), key=KEY, now=NOW)
    assert link.job_id == job.id
    assert link.technician_id == job.technician_id
    assert expires_at == job.scheduled_start + timedelta(hours=72)


def test_a_job_with_no_technician_has_no_link():
    job = Job(company_id=uuid4(), customer_id=uuid4(), title="Leak",
              scheduled_start=NOW + timedelta(days=2))
    with pytest.raises(ValueError):
        links.link_for_job(job, key=KEY, ttl=timedelta(hours=72), now=NOW)
