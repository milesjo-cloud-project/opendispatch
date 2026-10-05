"""Proves the status flow is enforced in the domain layer, with no database involved."""
from datetime import datetime, timezone
from itertools import product
from uuid import uuid4

import pytest

from app.shared.errors import DomainRuleViolation, IllegalTransition
from app.shared.job_status import ALLOWED, TERMINAL, JobStatus
from app.shared.models import Job

S = JobStatus

HAPPY_PATH = [
    S.SCHEDULED,
    S.DISPATCHED,
    S.EN_ROUTE,
    S.IN_PROGRESS,
    S.COMPLETED,
    S.INVOICED,
    S.PAID,
]


def make_job(status: JobStatus = S.REQUESTED) -> Job:
    return Job(
        company_id=uuid4(),
        customer_id=uuid4(),
        title="Clogged kitchen drain",
        status=status,
        technician_id=uuid4(),
        scheduled_start=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )


def test_happy_path_requested_to_paid():
    job = make_job()
    events = [job.transition_to(target) for target in HAPPY_PATH]

    assert job.status == S.PAID
    assert len(events) == 7
    assert events[0].from_status == S.REQUESTED
    assert events[-1].to_status == S.PAID
    assert all(e.job_id == job.id and e.company_id == job.company_id for e in events)


@pytest.mark.parametrize("current,target", list(product(JobStatus, JobStatus)))
def test_every_pair_matches_the_table(current, target):
    """All 81 combinations: allowed ones succeed, everything else raises."""
    job = make_job(status=current)
    if target in ALLOWED[current]:
        event = job.transition_to(target)
        assert job.status == target
        assert event.from_status == current
    else:
        with pytest.raises(IllegalTransition):
            job.transition_to(target)
        assert job.status == current  # unchanged after a failed move


def test_paid_and_cancelled_are_terminal():
    assert TERMINAL == {S.PAID, S.CANCELLED}


@pytest.mark.parametrize("status", [S.REQUESTED, S.SCHEDULED, S.DISPATCHED, S.EN_ROUTE, S.IN_PROGRESS])
def test_can_cancel_before_completed(status):
    job = make_job(status=status)
    job.transition_to(S.CANCELLED)
    assert job.status == S.CANCELLED


@pytest.mark.parametrize("status", [S.COMPLETED, S.INVOICED, S.PAID])
def test_cannot_cancel_after_completed(status):
    job = make_job(status=status)
    with pytest.raises(IllegalTransition):
        job.transition_to(S.CANCELLED)


def test_cannot_dispatch_without_technician():
    job = make_job(status=S.SCHEDULED)
    job.technician_id = None
    with pytest.raises(DomainRuleViolation):
        job.transition_to(S.DISPATCHED)
    assert job.status == S.SCHEDULED


def test_cannot_schedule_without_start_time():
    job = make_job()
    job.scheduled_start = None
    with pytest.raises(DomainRuleViolation):
        job.transition_to(S.SCHEDULED)
    assert job.status == S.REQUESTED


def test_event_records_actor_and_note():
    actor = uuid4()
    job = make_job()
    event = job.transition_to(S.SCHEDULED, actor_user_id=actor, note="Customer asked for morning")
    assert event.actor_user_id == actor
    assert event.note == "Customer asked for morning"
