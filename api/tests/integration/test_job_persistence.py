"""Saves a job and its events to real Postgres and reads them back.

Needs a migrated database at TEST_DATABASE_URL (CI provides one):
    alembic upgrade head
Skipped when TEST_DATABASE_URL isn't set or the database can't be reached.
"""
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.domain.entities import Company, Customer, Job, JobEvent, Technician, User
from app.domain.errors import IllegalTransition
from app.domain.job_status import JobStatus

pytestmark = pytest.mark.integration


@pytest.fixture
def session():
    from app.adapters.db.session import make_session_factory

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    try:
        factory = make_session_factory(url)
        s = factory()
        s.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"Postgres not available: {exc}")
    try:
        yield s
    finally:
        s.rollback()  # nothing from this test is kept
        s.close()


def test_job_and_events_round_trip(session):
    company = Company(name="Test Drain Co")
    owner = User(company_id=company.id, email=f"owner-{company.id}@example.com", role="owner")
    tech_user = User(company_id=company.id, email=f"tech-{company.id}@example.com", role="technician")
    tech = Technician(company_id=company.id, user_id=tech_user.id, display_name="Sam")
    customer = Customer(company_id=company.id, name="Jane Doe", phone="555-0100")
    job = Job(
        company_id=company.id,
        customer_id=customer.id,
        title="Main line clog",
        technician_id=tech.id,
        scheduled_start=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )

    session.add(company)
    session.flush()
    session.add_all([owner, tech_user])
    session.flush()
    session.add_all([tech, customer])
    session.flush()
    session.add(job)
    session.flush()

    event = job.transition_to(JobStatus.SCHEDULED, actor_user_id=owner.id)
    session.add(event)
    session.flush()

    # The illegal move fails in the domain, before any SQL runs.
    with pytest.raises(IllegalTransition):
        job.transition_to(JobStatus.PAID)

    session.expire_all()
    loaded = session.get(Job, job.id)
    assert loaded.status == JobStatus.SCHEDULED

    events = session.scalars(select(JobEvent).where(JobEvent.job_id == job.id)).all()
    assert len(events) == 1
    assert events[0].from_status == JobStatus.REQUESTED
    assert events[0].to_status == JobStatus.SCHEDULED


def test_database_rejects_unknown_status(session):
    """Belt and braces: the CHECK constraint blocks garbage even if someone bypasses the domain."""
    from sqlalchemy.exc import IntegrityError

    session.execute(text(
        "INSERT INTO companies (id, name, created_at) "
        "VALUES ('00000000-0000-0000-0000-00000000000a', 'x', now())"
    ))
    session.execute(text(
        "INSERT INTO customers (id, company_id, name, created_at) "
        "VALUES ('00000000-0000-0000-0000-00000000000b', '00000000-0000-0000-0000-00000000000a', 'c', now())"
    ))
    with pytest.raises(IntegrityError, match="check constraint"):
        session.execute(text(
            "INSERT INTO jobs (id, company_id, customer_id, title, status, created_at) "
            "VALUES (gen_random_uuid(), '00000000-0000-0000-0000-00000000000a', "
            "'00000000-0000-0000-0000-00000000000b', 't', 'teleported', now())"
        ))
