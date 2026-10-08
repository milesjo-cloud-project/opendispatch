"""The waitlist outbox: queueing a signup for the launch spreadsheet, and retrying.

Needs Postgres (the partial unique index and SKIP LOCKED are the point), so these are
skipped unless TEST_DATABASE_URL is set. See conftest.py. The waitlist is not
tenant-scoped, so no company fixture, and the table may already hold rows: every
assertion is about the signups this test made.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.adapters.sheets import FakeSheet
from app.db.tables import waitlist_outbox
from app.shared.outbox import MAX_ATTEMPTS, retry_after
from app.waitlist import service as waitlist
from app.waitlist import sync
from app.waitlist.sheet import COLUMNS, HEADER_ROW, row_for, row_number

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def an_email() -> str:
    return f"pat-{uuid4()}@example.com"


def joined(session, **fields):
    signup, _ = waitlist.join(session, email=an_email(), **fields)
    session.flush()
    return signup


def rows(session, signup):
    return session.execute(
        select(waitlist_outbox).where(waitlist_outbox.c.signup_id == signup.id)
    ).mappings().all()


def pending(session, signup):
    return [row for row in rows(session, signup) if row["sent_at"] is None]


# --- queueing

def test_queueing_a_signup_leaves_one_row_waiting(session):
    signup = joined(session)
    sync.mark_dirty(session, signup, now=NOW)
    assert len(pending(session, signup)) == 1


def test_queueing_the_same_signup_again_collapses_into_one_row(session):
    """Nothing should be able to put the same person in the sheet twice."""
    signup = joined(session)
    for _ in range(5):
        sync.mark_dirty(session, signup, now=NOW)
    assert len(pending(session, signup)) == 1


def test_queue_all_queues_every_signup(session):
    first, second = joined(session), joined(session)
    queued = sync.queue_all(session, now=NOW)

    assert queued >= 2
    assert len(pending(session, first)) == 1
    assert len(pending(session, second)) == 1


def test_queue_all_is_safe_to_run_twice(session):
    """It's the fix for a spreadsheet that was replaced, so it has to be re-runnable."""
    signup = joined(session)
    sync.queue_all(session, now=NOW)
    sync.queue_all(session, now=NOW)
    assert len(pending(session, signup)) == 1


# --- writing

def test_the_sync_writes_the_signup_to_the_row_its_spot_owns(session):
    signup = joined(session, name="Pat Jones", company="Jones Plumbing")
    sync.mark_dirty(session, signup, now=NOW)
    sheet = FakeSheet()

    assert sync.sync_pending(session, sheet, now=NOW) >= 1
    assert sheet.rows[row_number(signup)] == row_for(signup)
    assert sheet.rows[HEADER_ROW] == list(COLUMNS)
    assert pending(session, signup) == []


def test_a_signup_already_written_is_not_written_again(session):
    signup = joined(session)
    sync.mark_dirty(session, signup, now=NOW)
    sheet = FakeSheet()
    sync.sync_pending(session, sheet, now=NOW)
    before = len(sheet.writes)

    sync.sync_pending(session, sheet, now=NOW + timedelta(hours=1))
    assert len(sheet.writes) == before


def test_writing_the_same_signup_twice_overwrites_one_row(session):
    """Which is why a retry costs nothing: the sheet ends up the same either way."""
    signup = joined(session)
    sheet = FakeSheet()
    sync.sync_signup(session, sheet, signup.id)
    sync.sync_signup(session, sheet, signup.id)
    assert len(sheet.rows) == 2  # the header and this signup's row, not three rows


def test_a_write_for_a_signup_that_is_gone_is_not_an_error(session):
    """Deleted between queueing and sending. There's nothing to write and nothing to undo."""
    sheet = FakeSheet()
    sync.sync_signup(session, sheet, uuid4())  # must not raise
    assert sheet.writes == []


# --- retrying

def test_a_failed_write_stays_queued_with_its_next_try_pushed_out(session):
    signup = joined(session)
    sync.mark_dirty(session, signup, now=NOW)

    assert sync.sync_pending(session, FakeSheet(fail=True), now=NOW) == 0
    row = pending(session, signup)[0]
    assert row["attempts"] == 1
    assert row["next_attempt_at"] == NOW + retry_after(1)
    assert "down" in row["last_error"]


def test_a_write_that_is_not_due_yet_is_left_alone(session):
    signup = joined(session)
    sync.mark_dirty(session, signup, now=NOW)
    sync.sync_pending(session, FakeSheet(fail=True), now=NOW)

    sheet = FakeSheet()
    assert sync.sync_pending(session, sheet, now=NOW + retry_after(1) - timedelta(seconds=1)) == 0
    assert sheet.writes == []


def test_a_retry_after_the_provider_comes_back_lands_the_row(session):
    signup = joined(session)
    sync.mark_dirty(session, signup, now=NOW)
    sync.sync_pending(session, FakeSheet(fail=True), now=NOW)

    sheet = FakeSheet()
    later = NOW + retry_after(1)
    assert sync.sync_pending(session, sheet, now=later) >= 1
    assert sheet.rows[row_number(signup)] == row_for(signup)


def test_a_row_is_left_alone_after_too_many_attempts(session):
    """It stays in the table with last_error, rather than being retried forever."""
    signup = joined(session)
    sync.mark_dirty(session, signup, now=NOW)
    session.execute(waitlist_outbox.update()
                    .where(waitlist_outbox.c.signup_id == signup.id)
                    .values(attempts=MAX_ATTEMPTS))

    sheet = FakeSheet()
    assert sync.sync_pending(session, sheet, now=NOW + timedelta(days=2)) == 0
    assert sheet.writes == []
    assert len(pending(session, signup)) == 1


def test_a_fresh_queueing_resets_the_backoff(session):
    """A spreadsheet that's just been fixed shouldn't wait out the tail of the outage."""
    signup = joined(session)
    sync.mark_dirty(session, signup, now=NOW)
    sync.sync_pending(session, FakeSheet(fail=True), now=NOW)

    sync.mark_dirty(session, signup, now=NOW)
    row = pending(session, signup)[0]
    assert row["attempts"] == 0
    assert row["next_attempt_at"] == NOW
    assert row["last_error"] is None


def test_one_failure_does_not_stop_the_rest_of_the_batch(session):
    """Each write gets its own savepoint, so a bad row can't hold up the others."""
    first, second = joined(session), joined(session)
    sync.mark_dirty(session, first, now=NOW)
    sync.mark_dirty(session, second, now=NOW)

    class OneBadRow(FakeSheet):
        def write_rows(self, rows):
            if rows.get(row_number(first)):
                raise RuntimeError("Google Sheets refused the write: 400")
            super().write_rows(rows)

    sheet = OneBadRow()
    assert sync.sync_pending(session, sheet, now=NOW) >= 1
    assert row_number(second) in sheet.rows
    assert len(pending(session, first)) == 1
    assert pending(session, second) == []
