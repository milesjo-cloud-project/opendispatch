"""Budget vs. actual and the 80% / 100% alerts. No database."""
from uuid import uuid4

import pytest

from app.shared.models import Company, Job, User
from app.spend.budget import BudgetLevel, alert_for, job_budget, level_for

L = BudgetLevel
QUOTE = 100_000  # $1,000.00


@pytest.mark.parametrize("spent,level", [
    (0, L.OK),
    (79_999, L.OK),
    (80_000, L.WARNING),
    (99_999, L.WARNING),
    (100_000, L.OVER),
    (150_000, L.OVER),
])
def test_levels(spent, level):
    assert level_for(QUOTE, spent) == level


def test_no_quote():
    assert level_for(None, 999_999) == L.NO_QUOTE


def test_zero_quote_is_over_as_soon_as_anything_is_spent():
    assert level_for(0, 0) == L.OK
    assert level_for(0, 1) == L.OVER


@pytest.mark.parametrize("before,after,alert", [
    (0, 50_000, None),              # still under 80%
    (70_000, 80_000, L.WARNING),    # crosses 80%
    (85_000, 90_000, None),         # already warned
    (90_000, 100_000, L.OVER),      # crosses 100%
    (70_000, 120_000, L.OVER),      # jumps straight past both: one alert, the worse one
    (120_000, 130_000, None),       # already over
    (90_000, 50_000, None),         # spend went down (a rejection)
])
def test_alert_fires_once_per_threshold(before, after, alert):
    assert alert_for(QUOTE, before, after) == alert


def test_no_alerts_without_a_quote():
    assert alert_for(None, 0, 10_000_000) is None


def _setup():
    company = Company(name="Test Drain Co")
    owner = User(company_id=company.id, email="o@example.com", role="owner")
    tech = User(company_id=company.id, email="t@example.com", role="technician")
    job = Job(company_id=company.id, customer_id=uuid4(), title="Repipe", quoted_amount_cents=QUOTE)
    return company, owner, tech, job


def test_job_budget_counts_approved_and_pending_but_not_rejected():
    company, owner, tech, job = _setup()
    approved = job.add_expense(company, tech, 30_000)   # auto-approved
    pending = job.add_expense(company, tech, 60_000)    # over $500, waiting
    rejected = job.add_expense(company, tech, 55_000)
    rejected.reject(owner)

    budget = job_budget(job, [approved, pending, rejected])
    assert budget.approved_cents == 30_000
    assert budget.pending_cents == 60_000
    assert budget.spent_cents == 90_000
    assert budget.remaining_cents == 10_000
    assert budget.level == L.WARNING


def test_job_budget_goes_negative_when_over():
    company, _, tech, job = _setup()
    budget = job_budget(job, [job.add_expense(company, tech, 50_000),
                              job.add_expense(company, tech, 50_000),
                              job.add_expense(company, tech, 25_000)])
    assert budget.remaining_cents == -25_000
    assert budget.level == L.OVER


def test_job_budget_without_quote():
    company, _, tech, job = _setup()
    job.quoted_amount_cents = None
    budget = job_budget(job, [job.add_expense(company, tech, 1_000)])
    assert budget.remaining_cents is None
    assert budget.level == L.NO_QUOTE


def test_job_budget_refuses_another_jobs_expenses():
    company, _, tech, job = _setup()
    other = Job(company_id=company.id, customer_id=uuid4(), title="Other")
    with pytest.raises(ValueError):
        job_budget(job, [other.add_expense(company, tech, 1_000)])
