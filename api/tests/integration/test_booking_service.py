"""services/booking.py against a real database: the link, public submissions, and the office's decisions."""
import pytest
from sqlalchemy import func, select

from app.domain.booking import BookingRequestStatus
from app.domain.entities import Customer, Job, JobEvent
from app.domain.errors import DomainRuleViolation
from app.domain.job_status import JobStatus
from app.services import booking
from app.services.spend import NotFound

pytestmark = pytest.mark.integration


def customers_in(session, t) -> int:
    return session.scalar(select(func.count()).select_from(Customer).where(Customer.company_id == t.company.id))


def jobs_in(session, t) -> int:
    return session.scalar(select(func.count()).select_from(Job).where(Job.company_id == t.company.id))


def submit(session, t, **overrides):
    fields = dict(name="Pat Jones", title="Leaking tap", phone="555-0100")
    fields.update(overrides)
    return booking.submit(session, t.company.booking_id, **fields)


@pytest.fixture
def open_a(session, a):
    """Company A with online booking turned on."""
    booking.turn_on(a.company)
    session.flush()
    return a


# --- the link

def test_link_is_off_until_turned_on(session, a):
    assert a.company.booking_id is None
    with pytest.raises(NotFound):
        booking.company_for_booking_id(session, "")


def test_turn_on_replace_and_off(session, a):
    first = booking.turn_on(a.company)
    session.flush()
    assert len(first) == 12
    assert booking.company_for_booking_id(session, first) is a.company

    second = booking.turn_on(a.company)
    session.flush()
    assert second != first
    with pytest.raises(NotFound):
        booking.company_for_booking_id(session, first)  # the old link stops working

    booking.turn_off(a.company)
    session.flush()
    with pytest.raises(NotFound):
        booking.company_for_booking_id(session, second)


# --- public submissions

def test_submit_touches_no_customer_or_job(session, open_a):
    before = customers_in(session, open_a), jobs_in(session, open_a)
    r = submit(session, open_a, email="pat@example.com", preferred_time="mornings")
    assert r.status == BookingRequestStatus.NEW and r.company_id == open_a.company.id
    assert (customers_in(session, open_a), jobs_in(session, open_a)) == before


def test_submit_with_a_wrong_link(session, open_a):
    with pytest.raises(NotFound):
        booking.submit(session, "not-a-real-id", name="X", title="Y", phone="1")


def test_submit_needs_a_way_to_reach_them(session, open_a):
    with pytest.raises(DomainRuleViolation):
        submit(session, open_a, phone=None)


def test_inbox_shows_only_this_companys_new_requests_oldest_first(session, open_a, b):
    booking.turn_on(b.company)
    session.flush()
    first = submit(session, open_a, title="First")
    second = submit(session, open_a, title="Second")
    declined = submit(session, open_a, title="Spam")
    submit(session, b, title="Company B's")
    booking.decline(session, open_a.owner, declined.id)
    assert [r.id for r in booking.new_requests(session, open_a.company.id)] == [first.id, second.id]


# --- accept / decline

def test_accept_with_a_new_customer_from_the_request(session, open_a):
    r = submit(session, open_a, email="pat@example.com", address="1 Main St",
               description="Under the sink", preferred_time="weekday mornings")
    job = booking.accept(session, open_a.owner, r.id)

    customer = session.get(Customer, job.customer_id)
    assert (customer.company_id, customer.name, customer.phone, customer.email, customer.address) == (
        open_a.company.id, "Pat Jones", "555-0100", "pat@example.com", "1 Main St")
    assert (job.status, job.title) == (JobStatus.REQUESTED, "Leaking tap")
    assert job.description == "Under the sink\n\nPreferred time: weekday mornings"
    assert (r.status, r.job_id) == (BookingRequestStatus.ACCEPTED, job.id)
    event = session.scalars(select(JobEvent).where(JobEvent.job_id == job.id)).one()
    assert (event.from_status, event.to_status, event.note) == (None, JobStatus.REQUESTED, "Booked online")


def test_accept_for_an_existing_customer_creates_no_customer(session, open_a):
    r = submit(session, open_a)
    before = customers_in(session, open_a)
    job = booking.accept(session, open_a.owner, r.id, customer_id=open_a.customer.id)
    assert job.customer_id == open_a.customer.id
    assert customers_in(session, open_a) == before


def test_cant_accept_for_another_companys_customer(session, open_a, b):
    r = submit(session, open_a)
    with pytest.raises(DomainRuleViolation, match="Unknown customer"):
        booking.accept(session, open_a.owner, r.id, customer_id=b.customer.id)
    assert r.status == BookingRequestStatus.NEW


def test_another_company_cant_see_or_decide_a_request(session, open_a, b):
    r = submit(session, open_a)
    with pytest.raises(NotFound):
        booking.accept(session, b.owner, r.id)
    with pytest.raises(NotFound):
        booking.decline(session, b.owner, r.id)
    assert r.status == BookingRequestStatus.NEW


def test_a_request_becomes_one_job_at_most(session, open_a):
    r = submit(session, open_a)
    booking.accept(session, open_a.owner, r.id)
    jobs = jobs_in(session, open_a)
    with pytest.raises(DomainRuleViolation, match="already accepted"):
        booking.accept(session, open_a.owner, r.id)
    with pytest.raises(DomainRuleViolation):
        booking.decline(session, open_a.owner, r.id)
    assert jobs_in(session, open_a) == jobs


def test_decline(session, open_a):
    r = submit(session, open_a)
    booking.decline(session, open_a.owner, r.id)
    assert (r.status, r.decided_by_user_id, r.job_id) == (BookingRequestStatus.DECLINED, open_a.owner.id, None)
