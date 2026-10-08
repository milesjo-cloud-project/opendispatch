"""The calendar outbox: collapsing edits, converging on the right event, and retrying.

Needs Postgres (the partial unique index and SKIP LOCKED are the point), so these are
skipped unless TEST_DATABASE_URL is set. See conftest.py.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.adapters.calendar import FakeCalendar
from app.calendar.service import EventOptions, mark_dirty, sync_pending
from app.db.tables import calendar_outbox, job_calendar_events
from app.jobs import links
from app.shared.job_status import JobStatus
from app.shared.models import Technician, User
from app.shared.outbox import MAX_ATTEMPTS, retry_after

from .tenants import make_job

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
KEY = b"test-signing-key"
OPTIONS = EventOptions(base_url="https://app.example/", link_key=KEY,
                       link_ttl=timedelta(hours=72), duration=timedelta(minutes=90))


def scheduled_job(session, tenant, **overrides):
    """A job that wants a calendar event: assigned, timed, and on the schedule."""
    job = make_job(tenant, status=JobStatus.SCHEDULED, **overrides)
    session.add(job)
    session.flush()
    return job


def pending(session, job):
    return session.execute(
        select(calendar_outbox).where(calendar_outbox.c.job_id == job.id,
                                      calendar_outbox.c.sent_at.is_(None))
    ).mappings().all()


def rows(session, job):
    return session.execute(
        select(calendar_outbox).where(calendar_outbox.c.job_id == job.id)
        .order_by(calendar_outbox.c.created_at)
    ).mappings().all()


def event_row(session, job):
    return session.execute(
        select(job_calendar_events).where(job_calendar_events.c.job_id == job.id)
    ).mappings().one_or_none()


# --- queueing

def test_repeated_edits_collapse_into_one_pending_write(session, a):
    """Five edits in a minute must not mean five calls to Google."""
    job = scheduled_job(session, a)
    for _ in range(5):
        mark_dirty(session, job, now=NOW)
    assert len(pending(session, job)) == 1


def test_a_new_edit_resets_the_backoff_of_a_job_that_is_waiting(session, a):
    """A fresh edit deserves a fresh try, not the tail of an old outage."""
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    session.execute(calendar_outbox.update().where(calendar_outbox.c.job_id == job.id)
                    .values(attempts=4, next_attempt_at=NOW + timedelta(hours=2),
                            last_error="boom"))
    mark_dirty(session, job, now=NOW)
    row = pending(session, job)[0]
    assert (row["attempts"], row["next_attempt_at"], row["last_error"]) == (0, NOW, None)


def test_a_job_can_be_queued_again_after_its_last_write_went_out(session, a):
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    sync_pending(session, FakeCalendar(), now=NOW, options=OPTIONS)
    mark_dirty(session, job, now=NOW + timedelta(minutes=5))
    assert len(pending(session, job)) == 1
    assert len(rows(session, job)) == 2  # the sent one is kept as a record


# --- converging on the right event

def test_a_scheduled_job_gets_an_event_with_the_technicians_signed_link(session, a):
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    calendar = FakeCalendar()

    assert sync_pending(session, calendar, now=NOW, options=OPTIONS) == 1

    external_id = event_row(session, job)["external_id"]
    event = calendar.events[external_id]
    assert event.job_id == job.id
    assert event.ends_at == job.scheduled_start + timedelta(minutes=90)
    tech_user = session.get(User, session.get(Technician, job.technician_id).user_id)
    assert event.technician_email == tech_user.email

    # The link in the event is real, and opens this job for this technician
    token = event.description.split("/j/")[1].split()[0]
    link = links.verify(token, key=KEY, now=NOW)
    assert (link.job_id, link.technician_id) == (job.id, job.technician_id)
    assert pending(session, job) == []


def test_editing_a_job_moves_its_event_instead_of_making_a_second_one(session, a):
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    calendar = FakeCalendar()
    sync_pending(session, calendar, now=NOW, options=OPTIONS)
    first = event_row(session, job)["external_id"]

    job.reschedule(job.scheduled_start + timedelta(days=1))
    mark_dirty(session, job, now=NOW)
    sync_pending(session, calendar, now=NOW, options=OPTIONS)

    assert event_row(session, job)["external_id"] == first
    assert len(calendar.events) == 1
    assert calendar.events[first].starts_at == job.scheduled_start


def test_cancelling_a_job_takes_its_event_down(session, a):
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    calendar = FakeCalendar()
    sync_pending(session, calendar, now=NOW, options=OPTIONS)
    external_id = event_row(session, job)["external_id"]

    job.transition_to(JobStatus.CANCELLED)
    mark_dirty(session, job, now=NOW)
    sync_pending(session, calendar, now=NOW, options=OPTIONS)

    assert calendar.cancelled == [external_id]
    assert calendar.events == {}
    assert event_row(session, job) is None  # nothing left out there to update


def test_a_job_queued_and_then_cancelled_never_reaches_a_calendar(session, a):
    """The write that would have been undone is the one that never happens."""
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    job.transition_to(JobStatus.CANCELLED)
    calendar = FakeCalendar()

    sync_pending(session, calendar, now=NOW, options=OPTIONS)

    assert calendar.created == []
    assert event_row(session, job) is None


def test_unassigning_a_job_takes_its_event_down(session, a):
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    calendar = FakeCalendar()
    sync_pending(session, calendar, now=NOW, options=OPTIONS)

    job.assign(None)
    mark_dirty(session, job, now=NOW)
    sync_pending(session, calendar, now=NOW, options=OPTIONS)

    assert calendar.events == {}
    assert event_row(session, job) is None


def test_an_event_deleted_at_the_provider_is_made_again(session, a):
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    calendar = FakeCalendar()
    sync_pending(session, calendar, now=NOW, options=OPTIONS)
    first = event_row(session, job)["external_id"]

    calendar.events.clear()  # somebody deleted it in Google
    mark_dirty(session, job, now=NOW)
    assert sync_pending(session, calendar, now=NOW, options=OPTIONS) == 1

    second = event_row(session, job)["external_id"]
    assert second != first
    assert second in calendar.events


def test_the_event_goes_out_without_a_link_when_links_are_off(session, a):
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    calendar = FakeCalendar()

    sync_pending(session, calendar, now=NOW,
                 options=EventOptions(base_url="https://app.example", link_key=None))

    assert "/j/" not in calendar.created[0].description


def test_a_disabled_accounts_event_comes_down(session, a):
    """Their link dies with the account; the event has to go too, address and all."""
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    calendar = FakeCalendar()
    sync_pending(session, calendar, now=NOW, options=OPTIONS)
    external_id = event_row(session, job)["external_id"]

    tech_user = session.get(User, session.get(Technician, job.technician_id).user_id)
    tech_user.disable()
    mark_dirty(session, job, now=NOW)
    sync_pending(session, calendar, now=NOW, options=OPTIONS)

    assert calendar.cancelled == [external_id]
    assert event_row(session, job) is None


def test_a_technician_off_the_schedule_keeps_their_event(session, a):
    """Deactivating only stops new work going their way; today's job is still theirs."""
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    calendar = FakeCalendar()
    sync_pending(session, calendar, now=NOW, options=OPTIONS)

    session.get(Technician, job.technician_id).active = False
    mark_dirty(session, job, now=NOW)
    sync_pending(session, calendar, now=NOW, options=OPTIONS)

    assert calendar.cancelled == []
    assert event_row(session, job) is not None


# --- retrying

def test_a_failed_write_stays_queued_and_backs_off(session, a):
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)

    assert sync_pending(session, FakeCalendar(fail=True), now=NOW, options=OPTIONS) == 0

    row = pending(session, job)[0]
    assert row["attempts"] == 1
    assert row["next_attempt_at"] == NOW + retry_after(1)
    assert "calendar provider is down" in row["last_error"]


def test_a_write_that_failed_succeeds_on_the_next_pass(session, a):
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    sync_pending(session, FakeCalendar(fail=True), now=NOW, options=OPTIONS)

    later = NOW + retry_after(1)
    calendar = FakeCalendar()
    assert sync_pending(session, calendar, now=later, options=OPTIONS) == 1

    assert len(calendar.created) == 1
    assert pending(session, job) == []


def test_a_write_is_not_retried_before_its_next_attempt_is_due(session, a):
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    sync_pending(session, FakeCalendar(fail=True), now=NOW, options=OPTIONS)

    calendar = FakeCalendar()
    assert sync_pending(session, calendar, now=NOW + timedelta(seconds=5), options=OPTIONS) == 0
    assert calendar.created == []


class OneBadJob(FakeCalendar):
    """Fails for one job and works for everything else."""

    def __init__(self, job_id):
        super().__init__()
        self.job_id = job_id

    def create_event(self, event):
        if event.job_id == self.job_id:
            raise ConnectionError("that one job is cursed")
        return super().create_event(event)


def test_one_jobs_failure_does_not_stop_the_rest_of_the_batch(session, a):
    """Each row syncs in its own savepoint, so one bad job cannot poison the pass."""
    first = scheduled_job(session, a)
    second = scheduled_job(session, a, title="Second job")
    mark_dirty(session, first, now=NOW - timedelta(seconds=1))  # picked up first
    mark_dirty(session, second, now=NOW)

    calendar = OneBadJob(first.id)
    assert sync_pending(session, calendar, now=NOW, options=OPTIONS) == 1

    assert [e.title.split(" — ")[0] for e in calendar.created] == ["Second job"]
    assert pending(session, first)[0]["attempts"] == 1
    assert pending(session, second) == []
    assert event_row(session, second) is not None


def test_a_write_that_keeps_failing_is_eventually_left_alone(session, a):
    """It stays in the table with last_error, so somebody can see what happened."""
    job = scheduled_job(session, a)
    mark_dirty(session, job, now=NOW)
    session.execute(calendar_outbox.update().where(calendar_outbox.c.job_id == job.id)
                    .values(attempts=MAX_ATTEMPTS - 1))

    assert sync_pending(session, FakeCalendar(fail=True), now=NOW, options=OPTIONS) == 0
    assert pending(session, job)[0]["attempts"] == MAX_ATTEMPTS

    calendar = FakeCalendar()
    far_future = NOW + timedelta(days=30)
    assert sync_pending(session, calendar, now=far_future, options=OPTIONS) == 0
    assert calendar.created == []


def test_the_backoff_grows_and_then_levels_off():
    assert retry_after(1) == timedelta(seconds=30)
    assert retry_after(2) == timedelta(minutes=1)
    assert retry_after(3) == timedelta(minutes=2)
    assert retry_after(MAX_ATTEMPTS) == timedelta(hours=6)  # capped, not still doubling


def test_the_retries_span_long_enough_to_cover_an_overnight_outage():
    """A token that expired at 6pm has to still land the event when it's fixed at 9am."""
    total = sum((retry_after(n) for n in range(1, MAX_ATTEMPTS + 1)), timedelta())
    assert total > timedelta(hours=16)
