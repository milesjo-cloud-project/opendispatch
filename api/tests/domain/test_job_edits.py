"""What office staff can edit on a job at each stage. No database involved."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.domain.entities import Job
from app.domain.errors import DomainRuleViolation
from app.domain.job_status import JobStatus

S = JobStatus
NINE = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
TEN = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def make_job(status: JobStatus, **kw) -> Job:
    fields = dict(company_id=uuid4(), customer_id=uuid4(), title="Clogged drain", status=status,
                  technician_id=uuid4(), scheduled_start=NINE, quoted_amount_cents=50_000)
    return Job(**{**fields, **kw})


def refused(job: Job, edit) -> None:
    """The edit raises and the job is exactly as it was."""
    before = dict(vars(job))
    with pytest.raises(DomainRuleViolation):
        edit(job)
    assert vars(job) == before


# --- technician

@pytest.mark.parametrize("status", [S.REQUESTED, S.SCHEDULED, S.DISPATCHED, S.EN_ROUTE, S.IN_PROGRESS])
def test_technician_can_change_until_the_work_is_done(status):
    job = make_job(status)
    other = uuid4()
    job.assign(other)
    assert job.technician_id == other


@pytest.mark.parametrize("status", [S.COMPLETED, S.INVOICED, S.PAID, S.CANCELLED])
def test_technician_is_fixed_once_the_work_is_done(status):
    refused(make_job(status), lambda j: j.assign(uuid4()))


@pytest.mark.parametrize("status", [S.REQUESTED, S.SCHEDULED])
def test_unassigning_is_fine_before_dispatch(status):
    job = make_job(status)
    job.assign(None)
    assert job.technician_id is None


@pytest.mark.parametrize("status", [S.DISPATCHED, S.EN_ROUTE, S.IN_PROGRESS])
def test_a_dispatched_job_cant_lose_its_technician(status):
    refused(make_job(status), lambda j: j.assign(None))


# --- start time

@pytest.mark.parametrize("status", [S.REQUESTED, S.SCHEDULED, S.DISPATCHED])
def test_start_can_move_until_the_tech_is_on_the_way(status):
    job = make_job(status)
    job.reschedule(TEN)
    assert job.scheduled_start == TEN


@pytest.mark.parametrize("status", [S.EN_ROUTE, S.IN_PROGRESS, S.COMPLETED, S.INVOICED, S.PAID, S.CANCELLED])
def test_start_is_fixed_once_under_way(status):
    refused(make_job(status), lambda j: j.reschedule(TEN))


def test_only_a_draft_can_lose_its_start_time():
    draft = make_job(S.REQUESTED)
    draft.reschedule(None)
    assert draft.scheduled_start is None
    refused(make_job(S.SCHEDULED), lambda j: j.reschedule(None))
    refused(make_job(S.DISPATCHED), lambda j: j.reschedule(None))


# --- quote, title, description

@pytest.mark.parametrize("status", [S.REQUESTED, S.SCHEDULED, S.DISPATCHED, S.EN_ROUTE, S.IN_PROGRESS, S.COMPLETED])
def test_quote_can_change_until_invoiced(status):
    job = make_job(status)
    job.set_quote(75_000)
    job.set_quote(None)
    assert job.quoted_amount_cents is None


@pytest.mark.parametrize("status", [S.INVOICED, S.PAID, S.CANCELLED])
def test_quote_is_fixed_once_invoiced(status):
    refused(make_job(status), lambda j: j.set_quote(75_000))
    refused(make_job(status), lambda j: j.set_quote(None))


def test_quote_must_still_be_whole_cents():
    refused(make_job(S.REQUESTED), lambda j: j.set_quote(-1))
    refused(make_job(S.REQUESTED), lambda j: j.set_quote(True))


@pytest.mark.parametrize("status", [S.COMPLETED, S.INVOICED])
def test_details_can_be_fixed_after_the_work(status):
    job = make_job(status)
    job.rename("  Clogged kitchen drain ")
    job.set_description("Customer asked for a follow-up")
    assert (job.title, job.description) == ("Clogged kitchen drain", "Customer asked for a follow-up")


@pytest.mark.parametrize("status", [S.PAID, S.CANCELLED])
def test_paid_and_cancelled_jobs_are_final(status):
    refused(make_job(status), lambda j: j.rename("Something else"))
    refused(make_job(status), lambda j: j.set_description("Something else"))


def test_blank_title_is_refused():
    refused(make_job(S.REQUESTED), lambda j: j.rename("   "))


# --- re-sending what's already there

@pytest.mark.parametrize("status", list(S))
def test_unchanged_values_are_always_accepted(status):
    """The web app sends the technician and time on every save, even on a paid job."""
    job = make_job(status)
    job.assign(job.technician_id)
    job.reschedule(datetime(2026, 10, 1, 4, 0, tzinfo=timezone(timedelta(hours=-5))))  # 9:00 UTC, as sent from Missouri
    job.set_quote(50_000)
    job.rename("Clogged drain")
    job.set_description(None)
