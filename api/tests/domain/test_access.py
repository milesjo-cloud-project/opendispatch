"""Who can see which jobs, expenses and budgets. No database."""
from uuid import uuid4

import pytest

from app.domain.access import can_view_budget, can_view_expense, can_view_job
from app.domain.entities import Company, Job, Technician, User


@pytest.fixture
def company() -> Company:
    return Company(name="Test Drain Co")


def _user(company, role) -> User:
    return User(company_id=company.id, email=f"{role}-{uuid4()}@example.com", role=role)


def _tech(company, user) -> Technician:
    return Technician(company_id=company.id, user_id=user.id, display_name="Sam")


@pytest.fixture
def sam(company):
    user = _user(company, "technician")
    return user, _tech(company, user)


@pytest.fixture
def pat(company):
    user = _user(company, "technician")
    return user, _tech(company, user)


@pytest.fixture
def sams_job(company, sam) -> Job:
    return Job(company_id=company.id, customer_id=uuid4(), title="Leak", technician_id=sam[1].id)


@pytest.mark.parametrize("role", ["owner", "dispatcher"])
def test_office_sees_every_job(company, sams_job, role):
    assert can_view_job(_user(company, role), sams_job)
    unassigned = Job(company_id=company.id, customer_id=uuid4(), title="New")
    assert can_view_job(_user(company, role), unassigned)


def test_tech_sees_own_job(sam, sams_job):
    assert can_view_job(sam[0], sams_job, sam[1])


def test_tech_does_not_see_someone_elses_job(pat, sams_job):
    assert not can_view_job(pat[0], sams_job, pat[1])


def test_tech_does_not_see_unassigned_job(company, sam):
    job = Job(company_id=company.id, customer_id=uuid4(), title="New")
    assert not can_view_job(sam[0], job, sam[1])


def test_tech_without_profile_sees_nothing(company, sams_job):
    assert not can_view_job(_user(company, "technician"), sams_job, None)


def test_borrowed_tech_profile_does_not_work(pat, sam, sams_job):
    """Pat passing Sam's profile doesn't let Pat see Sam's job."""
    assert not can_view_job(pat[0], sams_job, sam[1])


@pytest.mark.parametrize("role", ["owner", "dispatcher", "technician"])
def test_nobody_sees_another_companys_job(sams_job, role):
    outsider = User(company_id=uuid4(), email="x@example.com", role=role)
    assert not can_view_job(outsider, sams_job)


def test_budget_is_office_only(company, sam, sams_job):
    assert can_view_budget(_user(company, "owner"), sams_job)
    assert can_view_budget(_user(company, "dispatcher"), sams_job)
    assert not can_view_budget(sam[0], sams_job)
    assert not can_view_budget(User(company_id=uuid4(), email="x@e.com", role="owner"), sams_job)


def test_expense_visibility(company, sam, sams_job):
    owner = _user(company, "owner")
    sams_expense = sams_job.add_expense(company, sam[0], 1_000)
    owners_expense = sams_job.add_expense(company, owner, 1_000)

    assert can_view_expense(owner, sams_expense, sams_job)
    assert can_view_expense(owner, owners_expense, sams_job)
    assert can_view_expense(sam[0], sams_expense, sams_job, sam[1])
    assert not can_view_expense(sam[0], owners_expense, sams_job, sam[1])  # not theirs


def test_expense_must_match_the_job(company, sam, sams_job):
    owner = _user(company, "owner")
    other_job = Job(company_id=company.id, customer_id=uuid4(), title="Other")
    expense = other_job.add_expense(company, owner, 1_000)
    assert not can_view_expense(owner, expense, sams_job)
