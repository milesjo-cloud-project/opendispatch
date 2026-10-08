"""When a job belongs on a calendar, and what the event says when it does."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.calendar.domain import MANAGED_NOTE, event_for, wants_event
from app.shared.job_status import JobStatus
from app.shared.models import Customer, Job

START = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def a_job(**overrides) -> Job:
    fields = dict(company_id=uuid4(), customer_id=uuid4(), title="Leak under the sink",
                  technician_id=uuid4(), scheduled_start=START, status=JobStatus.SCHEDULED)
    fields.update(overrides)
    return Job(**fields)


def a_customer(company_id, **overrides) -> Customer:
    fields = dict(company_id=company_id, name="Jane Doe", phone="+15551230000",
                  address="12 Elm St, Springfield")
    fields.update(overrides)
    return Customer(**fields)


# --- wants_event

@pytest.mark.parametrize("status", [JobStatus.SCHEDULED, JobStatus.DISPATCHED, JobStatus.EN_ROUTE,
                                    JobStatus.IN_PROGRESS, JobStatus.COMPLETED,
                                    JobStatus.INVOICED, JobStatus.PAID])
def test_a_scheduled_job_belongs_on_a_calendar(status):
    """Completed and later keep their event: the work happened, and the calendar is the record."""
    assert wants_event(a_job(status=status)) is True


def test_a_draft_does_not_belong_on_a_calendar():
    """A requested job is still an open shift; nobody has committed to it."""
    assert wants_event(a_job(status=JobStatus.REQUESTED)) is False


def test_cancelling_takes_a_job_off_the_calendar():
    assert wants_event(a_job(status=JobStatus.CANCELLED)) is False


def test_a_job_with_nobody_assigned_has_no_calendar_to_be_on():
    assert wants_event(a_job(technician_id=None)) is False


def test_a_job_with_no_time_cannot_be_an_event():
    assert wants_event(a_job(scheduled_start=None)) is False


# --- event_for

def test_the_event_carries_the_address_the_contact_and_the_link():
    job = a_job(description="Cupboard is soaked.")
    customer = a_customer(job.company_id)
    event = event_for(job, customer, "tech@example.com", link="https://app.example/j/tok",
                      duration=timedelta(minutes=90))

    assert event.job_id == job.id
    assert customer.name in event.title and job.title in event.title
    assert event.starts_at == START
    assert event.ends_at == START + timedelta(minutes=90)
    assert event.technician_email == "tech@example.com"
    assert event.location == customer.address
    for expected in (customer.name, customer.phone, customer.address,
                     "Cupboard is soaked.", "https://app.example/j/tok", MANAGED_NOTE):
        assert expected in event.description


def test_the_event_holds_together_without_a_customer_or_a_link():
    """Links are off when JOB_LINK_SECRET isn't set; the event still has to be worth having."""
    job = a_job()
    event = event_for(job, None, "tech@example.com", link=None)
    assert event.title == job.title
    assert event.location is None
    assert "/j/" not in event.description
    assert MANAGED_NOTE in event.description


def test_the_event_never_mentions_the_quote():
    """It goes to a calendar the company doesn't control, so money stays out of it."""
    job = a_job(quoted_amount_cents=125_000)
    event = event_for(job, a_customer(job.company_id), "tech@example.com")
    assert "1250" not in event.description and "125000" not in event.description


def test_a_job_that_does_not_want_an_event_cannot_make_one():
    with pytest.raises(ValueError):
        event_for(a_job(scheduled_start=None), None, "tech@example.com")
