"""Labor: logging time on a job and what it costs. No database."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.shared.errors import DomainRuleViolation
from app.shared.job_status import JobStatus
from app.shared.models import Company, Job, Technician, User
from app.spend.budget import BudgetAlert, BudgetLevel, job_budget

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
RATE = 6_000  # $60.00/hour


@pytest.fixture
def company() -> Company:
    return Company(name="Test Drain Co")


@pytest.fixture
def tech(company) -> Technician:
    return Technician(company_id=company.id, user_id=uuid4(), display_name="Sam", hourly_rate_cents=RATE)


@pytest.fixture
def job(company, tech) -> Job:
    return Job(company_id=company.id, customer_id=uuid4(), title="Repipe",
               technician_id=tech.id, quoted_amount_cents=100_000)


def test_log_time_copies_the_rate(job, tech):
    entry = job.log_time(tech, T0, T0 + timedelta(hours=2), note="Rough-in")
    assert entry.job_id == job.id
    assert entry.technician_id == tech.id
    assert entry.hourly_rate_cents == RATE

    tech.hourly_rate_cents = 9_000  # a raise later doesn't change past entries
    assert entry.labor_cost_cents == 12_000


@pytest.mark.parametrize("minutes,cents", [
    (60, 6_000),
    (90, 9_000),
    (1, 100),
    (7, 700),
])
def test_labor_cost(job, tech, minutes, cents):
    assert job.log_time(tech, T0, T0 + timedelta(minutes=minutes)).labor_cost_cents == cents


def test_labor_cost_rounds_to_nearest_cent(job, tech):
    tech.hourly_rate_cents = 1  # 1 cent/hour
    assert job.log_time(tech, T0, T0 + timedelta(minutes=29)).labor_cost_cents == 0
    assert job.log_time(tech, T0, T0 + timedelta(minutes=30)).labor_cost_cents == 1


def test_only_assigned_tech_can_log_time(company, job):
    other = Technician(company_id=company.id, user_id=uuid4(), display_name="Pat", hourly_rate_cents=RATE)
    with pytest.raises(DomainRuleViolation, match="assigned"):
        job.log_time(other, T0, T0 + timedelta(hours=1))


def test_tech_from_another_company_cannot_log_time(job, tech):
    tech.company_id = uuid4()
    with pytest.raises(DomainRuleViolation, match="same company"):
        job.log_time(tech, T0, T0 + timedelta(hours=1))


def test_needs_an_hourly_rate(job, tech):
    tech.hourly_rate_cents = None
    with pytest.raises(DomainRuleViolation, match="hourly rate"):
        job.log_time(tech, T0, T0 + timedelta(hours=1))


@pytest.mark.parametrize("end", [T0, T0 - timedelta(minutes=5)])
def test_end_must_be_after_start(job, tech, end):
    with pytest.raises(DomainRuleViolation, match="after start"):
        job.log_time(tech, T0, end)


def test_entry_capped_at_24_hours(job, tech):
    job.log_time(tech, T0, T0 + timedelta(hours=24))
    with pytest.raises(DomainRuleViolation, match="24 hours"):
        job.log_time(tech, T0, T0 + timedelta(hours=24, minutes=1))


def test_times_need_a_time_zone(job, tech):
    naive = datetime(2026, 10, 1, 8, 0)
    with pytest.raises(DomainRuleViolation, match="time zone"):
        job.log_time(tech, naive, naive + timedelta(hours=1))


@pytest.mark.parametrize("status", [JobStatus.PAID, JobStatus.CANCELLED])
def test_no_time_on_closed_jobs(job, tech, status):
    job.status = status
    with pytest.raises(DomainRuleViolation):
        job.log_time(tech, T0, T0 + timedelta(hours=1))


def test_negative_rate_is_rejected(company):
    with pytest.raises(DomainRuleViolation):
        Technician(company_id=company.id, user_id=uuid4(), display_name="X", hourly_rate_cents=-1)


def test_labor_counts_toward_budget(company, job, tech):
    user = User(company_id=company.id, email="t@example.com", role="technician")
    expense = job.add_expense(company, user, 40_000)
    entry = job.log_time(tech, T0, T0 + timedelta(hours=7))  # $420

    budget = job_budget(job, [expense], [entry])
    assert budget.labor_cents == 42_000
    assert budget.spent_cents == 82_000
    assert budget.level == BudgetLevel.WARNING


def test_budget_refuses_another_jobs_time(company, job, tech):
    other = Job(company_id=company.id, customer_id=uuid4(), title="Other", technician_id=tech.id)
    with pytest.raises(ValueError):
        job_budget(job, [], [other.log_time(tech, T0, T0 + timedelta(hours=1))])


def test_budget_alert_check(job, tech):
    before = job_budget(job, [])
    after = job_budget(job, [], [job.log_time(tech, T0, T0 + timedelta(hours=14))])  # $840
    alert = BudgetAlert.check(job, before, after)
    assert alert.level == BudgetLevel.WARNING
    assert alert.job_id == job.id and alert.company_id == job.company_id
    assert (alert.quoted_cents, alert.spent_cents) == (100_000, 84_000)
    assert alert.sent_at is None

    assert BudgetAlert.check(job, after, after) is None
