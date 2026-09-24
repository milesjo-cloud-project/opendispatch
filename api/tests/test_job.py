import pytest

from app.adapters.calendar.fake import FakeCalendar
from app.domain.job import InvalidTransition, Job, JobStatus


def make_job() -> Job:
    return Job(customer_name="Test Customer", address="123 Main St", description="Clogged drain")


def test_happy_path_to_paid():
    job = make_job()
    for s in [JobStatus.SCHEDULED, JobStatus.EN_ROUTE, JobStatus.IN_PROGRESS,
              JobStatus.COMPLETED, JobStatus.APPROVED, JobStatus.PAID]:
        job.move_to(s)
    assert job.status is JobStatus.PAID


def test_cannot_pay_before_approval():
    job = make_job()
    with pytest.raises(InvalidTransition):
        job.move_to(JobStatus.PAID)


def test_fake_calendar_round_trip():
    cal = FakeCalendar()
    job = make_job()
    event_id = cal.create_event(job, "tech@example.com")
    assert event_id in cal.events
    cal.cancel_event(event_id)
    assert event_id not in cal.events
