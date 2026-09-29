"""Expenses saved to real Postgres, and the constraints that back up the domain rules.

Needs a migrated database at TEST_DATABASE_URL (see conftest.py).
"""
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.domain.budget import BudgetLevel, job_budget
from app.domain.entities import Expense, ExpenseStatus, Job

from .test_tenant_integrity import Tenant, a, b, make_job  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture
def job(session, a) -> Job:
    job = make_job(a, quoted_amount_cents=100_000)
    session.add(job)
    session.flush()
    return job


def test_new_company_gets_500_dollar_limit(session, a):
    session.expire_all()
    assert session.get(type(a.company), a.company.id).expense_approval_limit_cents == 50_000


def test_expenses_round_trip_and_budget(session, a, job):
    small = job.add_expense(a.company, a.owner, 30_000, vendor="Home Depot")
    tech_user = session.get(type(a.owner), a.tech.user_id)
    big = job.add_expense(a.company, tech_user, 60_000, vendor="Ferguson")
    session.add_all([small, big])
    session.flush()
    big.approve(a.owner, note="ok")
    session.flush()

    session.expire_all()
    loaded = session.scalars(select(Expense).where(Expense.job_id == job.id)).all()
    assert {e.status for e in loaded} == {ExpenseStatus.APPROVED}
    assert session.get(Job, job.id).quoted_amount_cents == 100_000

    budget = job_budget(job, loaded)
    assert budget.spent_cents == 90_000
    assert budget.level == BudgetLevel.WARNING


def test_expense_cannot_point_at_another_companys_job(session, a, b, job):
    expense = job.add_expense(a.company, a.owner, 1_000)
    b_job = make_job(b)
    session.add(b_job)
    session.flush()
    expense.job_id = b_job.id  # bypassing the domain on purpose
    session.add(expense)
    with pytest.raises(IntegrityError, match="fk_expenses_job_same_company"):
        session.flush()


def test_decider_must_be_in_same_company(session, a, b, job):
    tech_user = session.get(type(a.owner), a.tech.user_id)
    expense = job.add_expense(a.company, tech_user, 60_000)
    session.add(expense)
    session.flush()
    expense.approve(a.owner)
    expense.decided_by_user_id = b.owner.id  # bypassing the domain on purpose
    with pytest.raises(IntegrityError, match="fk_expenses_decider_same_company"):
        session.flush()


def _insert(session, t: Tenant, job_id, amount, status, decided_at="NULL"):
    session.execute(text(
        "INSERT INTO expenses (id, company_id, job_id, submitted_by_user_id, amount_cents, "
        f"status, decided_at, created_at) VALUES (gen_random_uuid(), :c, :j, :u, :amt, :s, {decided_at}, now())"
    ), {"c": t.company.id, "j": job_id, "u": t.owner.id, "amt": amount, "s": status})


@pytest.mark.parametrize("amount", [0, -500])
def test_database_rejects_non_positive_amount(session, a, job, amount):
    with pytest.raises(IntegrityError, match="ck_expenses_amount_positive"):
        _insert(session, a, job.id, amount, "pending")


def test_database_rejects_unknown_status(session, a, job):
    with pytest.raises(IntegrityError, match="ck_expenses_expense_status"):
        _insert(session, a, job.id, 1_000, "maybe", "now()")


def test_database_rejects_approved_without_decision_time(session, a, job):
    with pytest.raises(IntegrityError, match="ck_expenses_decided_at_matches_status"):
        _insert(session, a, job.id, 1_000, "approved")


def test_database_rejects_negative_quote(session, job):
    with pytest.raises(IntegrityError, match="ck_jobs_quote_not_negative"):
        session.execute(text("UPDATE jobs SET quoted_amount_cents = -1 WHERE id = :j"), {"j": job.id})
