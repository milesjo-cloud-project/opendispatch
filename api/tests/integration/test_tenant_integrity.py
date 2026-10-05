"""Postgres itself blocks cross-company references, bad roles, duplicate emails,
and edits to job history, even if application code gets it wrong."""
from uuid import uuid4

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.tables import job_events, jobs
from app.shared.job_status import JobStatus
from app.shared.models import Job, Technician, User

from .tenants import make_job

pytestmark = pytest.mark.integration


def test_job_cannot_use_another_companys_customer(session, a, b):
    session.add(make_job(a, customer_id=b.customer.id))
    with pytest.raises(IntegrityError, match="fk_jobs_customer_same_company"):
        session.flush()


def test_job_cannot_use_another_companys_technician(session, a, b):
    session.add(make_job(a, technician_id=b.tech.id))
    with pytest.raises(IntegrityError, match="fk_jobs_technician_same_company"):
        session.flush()


def test_technician_cannot_link_to_another_companys_user(session, a, b):
    session.add(Technician(company_id=a.company.id, user_id=b.owner.id, display_name="X"))
    with pytest.raises(IntegrityError, match="fk_technicians_user_same_company"):
        session.flush()


def test_event_actor_must_be_in_same_company(session, a, b):
    job = make_job(a)
    session.add(job)
    session.flush()
    session.add(job.transition_to(JobStatus.SCHEDULED, actor_user_id=b.owner.id))
    with pytest.raises(IntegrityError, match="fk_job_events_actor_same_company"):
        session.flush()


def test_email_is_unique_regardless_of_case(session, a):
    email = f"Bob-{uuid4()}@Example.com"
    session.add(User(company_id=a.company.id, email=email, role="dispatcher"))
    session.flush()
    with pytest.raises(IntegrityError, match="uq_users_email_lower"):
        session.execute(text(
            "INSERT INTO users (id, company_id, email, role, created_at) "
            "VALUES (gen_random_uuid(), :c, :e, 'dispatcher', now())"
        ), {"c": a.company.id, "e": email.upper()})


def test_database_rejects_unknown_role(session, a):
    with pytest.raises(IntegrityError, match="ck_users_user_role"):
        session.execute(text(
            "INSERT INTO users (id, company_id, email, role, created_at) "
            "VALUES (gen_random_uuid(), :c, :e, 'superadmin', now())"
        ), {"c": a.company.id, "e": f"x-{uuid4()}@example.com"})


@pytest.fixture
def job_with_history(session, a) -> Job:
    job = make_job(a)
    session.add(job)
    session.flush()
    session.add(job.transition_to(JobStatus.SCHEDULED, actor_user_id=a.owner.id))
    session.flush()
    return job


def test_job_history_cannot_be_edited(session, job_with_history):
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(update(job_events).where(job_events.c.job_id == job_with_history.id)
                        .values(note="rewritten"))


def test_job_history_cannot_be_deleted(session, job_with_history):
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(delete(job_events).where(job_events.c.job_id == job_with_history.id))


def test_job_with_history_cannot_be_deleted(session, job_with_history):
    with pytest.raises(IntegrityError, match="fk_job_events_job_same_company"):
        session.execute(delete(jobs).where(jobs.c.id == job_with_history.id))
