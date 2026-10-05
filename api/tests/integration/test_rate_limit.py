"""shared/rate_limit.py against a real database."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.tables import rate_limit_hits
from app.shared import rate_limit

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def allow(session, key="203.0.113.7", bucket="test", now=NOW, limit=3):
    return rate_limit.allow(session, bucket, key, limit=limit, window=HOUR, now=now)


def test_allows_up_to_the_limit_then_refuses(session):
    assert [allow(session) for _ in range(4)] == [True, True, True, False]


def test_keys_and_buckets_are_counted_separately(session):
    for _ in range(3):
        allow(session)
    assert allow(session) is False
    assert allow(session, key="198.51.100.1") is True
    assert allow(session, bucket="other") is True


def test_hits_age_out_after_the_window(session):
    for minutes in (0, 10, 20):
        allow(session, now=NOW + timedelta(minutes=minutes))
    assert allow(session, now=NOW + timedelta(minutes=30)) is False
    # An hour after the first hit, that one no longer counts
    assert allow(session, now=NOW + timedelta(minutes=60)) is True


def test_refused_hits_dont_extend_the_wait(session):
    for _ in range(3):
        allow(session)
    for minutes in range(1, 50, 7):  # keeps hammering
        assert allow(session, now=NOW + timedelta(minutes=minutes)) is False
    assert allow(session, now=NOW + HOUR) is True


def test_old_rows_are_deleted_and_addresses_arent_stored(session):
    allow(session, now=NOW - 2 * HOUR)
    allow(session)
    rows = session.execute(select(rate_limit_hits.c.key_hash).where(rate_limit_hits.c.bucket == "test")).all()
    assert len(rows) == 1  # the two-hour-old hit was deleted
    assert "203.0.113.7" not in rows[0].key_hash
