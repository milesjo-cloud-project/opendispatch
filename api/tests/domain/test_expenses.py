"""Expense rules: job coding, the owner-approval limit, and who may decide. No database."""
from uuid import uuid4

import pytest

from app.shared.errors import DomainRuleViolation
from app.shared.job_status import JobStatus
from app.shared.models import Company, Customer, ExpenseStatus, Job, User

LIMIT = 50_000  # $500.00


@pytest.fixture
def company() -> Company:
    return Company(name="Test Drain Co")


@pytest.fixture
def owner(company) -> User:
    return User(company_id=company.id, email="owner@example.com", role="owner")


@pytest.fixture
def tech(company) -> User:
    return User(company_id=company.id, email="tech@example.com", role="technician")


@pytest.fixture
def job(company) -> Job:
    customer = Customer(company_id=company.id, name="Jane Doe")
    return Job(company_id=company.id, customer_id=customer.id, title="Water heater swap",
               quoted_amount_cents=200_000)


def test_default_approval_limit_is_500_dollars(company):
    assert company.expense_approval_limit_cents == LIMIT


def test_expense_is_coded_to_the_job(company, tech, job):
    expense = job.add_expense(company, tech, 12_345, vendor="Ferguson")
    assert expense.job_id == job.id
    assert expense.company_id == company.id
    assert expense.submitted_by_user_id == tech.id
    assert expense.amount_cents == 12_345


@pytest.mark.parametrize("amount", [1, 12_000, LIMIT])
def test_at_or_under_limit_is_approved_automatically(company, tech, job, amount):
    expense = job.add_expense(company, tech, amount)
    assert expense.status == ExpenseStatus.APPROVED
    assert expense.decided_at is not None
    assert expense.decided_by_user_id is None


@pytest.mark.parametrize("amount", [LIMIT + 1, 180_000])
def test_over_limit_waits_for_owner(company, tech, job, amount):
    expense = job.add_expense(company, tech, amount)
    assert expense.status == ExpenseStatus.PENDING
    assert expense.decided_at is None


def test_limit_is_per_company(tech, job, company):
    company.expense_approval_limit_cents = 10_000
    assert job.add_expense(company, tech, 10_001).status == ExpenseStatus.PENDING


def test_owners_own_spend_is_not_held_for_themselves(company, owner, job):
    assert job.add_expense(company, owner, 180_000).status == ExpenseStatus.APPROVED


@pytest.mark.parametrize("amount", [0, -100, 12.5, "500", True])
def test_amount_must_be_positive_whole_cents(company, tech, job, amount):
    with pytest.raises(DomainRuleViolation):
        job.add_expense(company, tech, amount)


@pytest.mark.parametrize("status", [JobStatus.PAID, JobStatus.CANCELLED])
def test_no_expenses_on_closed_jobs(company, tech, job, status):
    job.status = status
    with pytest.raises(DomainRuleViolation):
        job.add_expense(company, tech, 1_000)


def test_submitter_must_be_in_jobs_company(company, job):
    outsider = User(company_id=uuid4(), email="x@example.com", role="technician")
    with pytest.raises(DomainRuleViolation):
        job.add_expense(company, outsider, 1_000)


def test_company_must_be_the_jobs_company(tech, job):
    with pytest.raises(DomainRuleViolation):
        job.add_expense(Company(name="Other"), tech, 1_000)


def test_owner_approves(company, owner, tech, job):
    expense = job.add_expense(company, tech, 90_000)
    expense.approve(owner, note="Needed the bigger tank")
    assert expense.status == ExpenseStatus.APPROVED
    assert expense.decided_by_user_id == owner.id
    assert expense.decided_at is not None
    assert expense.decision_note == "Needed the bigger tank"


def test_owner_rejects(company, owner, tech, job):
    expense = job.add_expense(company, tech, 90_000)
    expense.reject(owner, note="Use the stock part")
    assert expense.status == ExpenseStatus.REJECTED
    assert expense.decided_by_user_id == owner.id


@pytest.mark.parametrize("role", ["technician", "dispatcher"])
def test_only_owner_can_decide(company, tech, job, role):
    expense = job.add_expense(company, tech, 90_000)
    someone = User(company_id=company.id, email=f"{role}2@example.com", role=role)
    with pytest.raises(DomainRuleViolation):
        expense.approve(someone)
    assert expense.status == ExpenseStatus.PENDING


def test_another_companys_owner_cannot_decide(company, tech, job):
    expense = job.add_expense(company, tech, 90_000)
    other_owner = User(company_id=uuid4(), email="boss@other.com", role="owner")
    with pytest.raises(DomainRuleViolation):
        expense.approve(other_owner)


def test_decision_is_final(company, owner, tech, job):
    expense = job.add_expense(company, tech, 90_000)
    expense.reject(owner)
    with pytest.raises(DomainRuleViolation):
        expense.approve(owner)
    assert expense.status == ExpenseStatus.REJECTED


def test_auto_approved_expense_cannot_be_decided_again(company, owner, tech, job):
    expense = job.add_expense(company, tech, 1_000)
    with pytest.raises(DomainRuleViolation):
        expense.reject(owner)


def test_negative_quote_is_rejected(company):
    with pytest.raises(DomainRuleViolation):
        Job(company_id=company.id, customer_id=uuid4(), title="x", quoted_amount_cents=-1)


def test_negative_approval_limit_is_rejected():
    with pytest.raises(DomainRuleViolation):
        Company(name="x", expense_approval_limit_cents=-1)
