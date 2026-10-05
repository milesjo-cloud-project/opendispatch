"""Booking requests in Postgres. The constraints hold even when application code skips the
domain rules, which is why several tests here set fields directly instead of calling accept()."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError

from app.booking.domain import BookingRequest, BookingRequestStatus
from app.db.tables import booking_requests, metadata

from .tenants import make_job

pytestmark = pytest.mark.integration


def request(t, **overrides) -> BookingRequest:
    fields = dict(company_id=t.company.id, name="Pat Jones", title="Leaking tap", phone="555-0100")
    fields.update(overrides)
    return BookingRequest(**fields)


def force_accepted(r: BookingRequest, job_id) -> None:
    """What buggy code might do: mark it accepted without going through accept()."""
    r.status = BookingRequestStatus.ACCEPTED
    r.job_id = job_id
    r.decided_at = datetime.now(timezone.utc)


def test_request_round_trips(session, a):
    r = request(a, email="pat@example.com", preferred_time="weekday mornings")
    session.add(r)
    session.flush()
    session.expire_all()
    loaded = session.get(BookingRequest, r.id)
    assert loaded.status == BookingRequestStatus.NEW
    assert (loaded.email, loaded.preferred_time) == ("pat@example.com", "weekday mornings")


def test_accepted_request_keeps_its_job(session, a):
    job = make_job(a)
    session.add(job)
    session.flush()
    r = request(a)
    r.accept(job, a.owner)
    session.add(r)
    session.flush()
    session.expire_all()
    assert session.get(BookingRequest, r.id).job_id == job.id


def test_request_cannot_point_at_another_companys_job(session, a, b):
    job = make_job(b)
    session.add(job)
    session.flush()
    r = request(a)
    force_accepted(r, job.id)
    session.add(r)
    with pytest.raises(IntegrityError, match="fk_booking_requests_job_same_company"):
        session.flush()


def test_decider_must_be_in_same_company(session, a, b):
    r = request(a)
    r.status, r.decided_at, r.decided_by_user_id = (
        BookingRequestStatus.DECLINED, datetime.now(timezone.utc), b.owner.id)
    session.add(r)
    with pytest.raises(IntegrityError, match="fk_booking_requests_decider_same_company"):
        session.flush()


def test_accepted_needs_a_job(session, a):
    r = request(a)
    force_accepted(r, None)
    session.add(r)
    with pytest.raises(IntegrityError, match="ck_booking_requests_job_matches_status"):
        session.flush()


def test_one_job_per_request(session, a):
    job = make_job(a)
    session.add(job)
    session.flush()
    first, second = request(a), request(a)
    force_accepted(first, job.id)
    force_accepted(second, job.id)
    session.add_all([first, second])
    with pytest.raises(IntegrityError, match="uq_booking_requests_job_id"):
        session.flush()


def test_request_needs_a_phone_or_email(session, a):
    with pytest.raises(IntegrityError, match="ck_booking_requests_has_contact"):
        session.execute(booking_requests.insert().values(
            id=uuid4(), company_id=a.company.id, name="X", title="Y", status="new",
            created_at=datetime.now(timezone.utc)))


def test_booking_ids_are_unique(session, a, b):
    a.company.booking_id = b.company.booking_id = "same-id-123"
    with pytest.raises(IntegrityError, match="uq_companies_booking_id"):
        session.flush()


def test_migration_matches_tables_py(session):
    """Migrations are written by hand; this catches one that drifts from tables.py."""
    diffs = compare_metadata(MigrationContext.configure(session.connection()), metadata)
    ours = [d for d in diffs if "booking" in repr(d) or "rate_limit" in repr(d)]
    assert ours == []
