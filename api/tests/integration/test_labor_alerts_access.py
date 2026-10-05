"""Time tracking, budget alerts end to end, and job visibility, against real Postgres.

Needs a migrated database at TEST_DATABASE_URL (see conftest.py).
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.adapters.notifications import FakeNotifier
from app.db.queries import visible_expenses, visible_job, visible_jobs
from app.shared.errors import DomainRuleViolation
from app.shared.models import Expense, Job, TimeEntry, User
from app.spend.budget import BudgetAlert, BudgetLevel
from app.spend.service import NotFound, log_time, send_pending_alerts, submit_expense

from .tenants import Tenant, make_job

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


def tech_user(session, t: Tenant) -> User:
    return session.get(User, t.tech.user_id)


@pytest.fixture
def job(session, a) -> Job:
    a.tech.hourly_rate_cents = 6_000  # $60/hour
    job = make_job(a, quoted_amount_cents=100_000)  # $1,000 quote
    session.add(job)
    session.flush()
    return job


def alerts_for(session, job) -> list[BudgetAlert]:
    return list(session.scalars(select(BudgetAlert).where(BudgetAlert.job_id == job.id)))


# --- spend service and alerts

def test_expense_under_80_percent_records_no_alert(session, a, job):
    result = submit_expense(session, job_id=job.id, submitted_by_user_id=a.owner.id, amount_cents=50_000)
    assert result.alert is None
    assert result.budget.spent_cents == 50_000
    assert alerts_for(session, job) == []


def test_crossing_80_then_100_records_each_alert_once(session, a, job):
    submit_expense(session, job_id=job.id, submitted_by_user_id=a.owner.id, amount_cents=70_000)
    warn = submit_expense(session, job_id=job.id, submitted_by_user_id=a.owner.id, amount_cents=15_000)
    assert warn.alert.level == BudgetLevel.WARNING

    again = submit_expense(session, job_id=job.id, submitted_by_user_id=a.owner.id, amount_cents=5_000)
    assert again.alert is None  # 90%: already warned

    over = log_time(session, job_id=job.id, technician_id=a.tech.id,
                    started_at=T0, ended_at=T0 + timedelta(hours=2))  # +$120 -> $1,020
    assert over.alert.level == BudgetLevel.OVER
    assert over.budget.labor_cents == 12_000

    assert sorted(x.level.value for x in alerts_for(session, job)) == ["over", "warning"]


def test_existing_alert_is_not_duplicated(session, a, job):
    """If the alert row already exists (e.g. the quote was raised and spend crossed 80% again),
    the insert is skipped instead of failing the expense."""
    session.add(BudgetAlert(a.company.id, job.id, BudgetLevel.WARNING, 100_000, 80_000))
    session.flush()
    result = submit_expense(session, job_id=job.id, submitted_by_user_id=a.owner.id, amount_cents=85_000)
    assert result.alert is None
    assert len(alerts_for(session, job)) == 1


def test_pending_expense_from_tech_still_counts(session, a, job):
    result = submit_expense(session, job_id=job.id, submitted_by_user_id=a.tech.user_id,
                            amount_cents=90_000)  # over $500: pending
    assert result.item.status.value == "pending"
    assert result.alert.level == BudgetLevel.WARNING


def test_rule_violation_saves_nothing(session, a, job):
    with pytest.raises(DomainRuleViolation):
        submit_expense(session, job_id=job.id, submitted_by_user_id=a.owner.id, amount_cents=0)
    assert session.scalars(select(Expense).where(Expense.job_id == job.id)).all() == []


def test_unknown_ids_raise_not_found(session, a, job):
    with pytest.raises(NotFound):
        submit_expense(session, job_id=uuid4(), submitted_by_user_id=a.owner.id, amount_cents=100)
    with pytest.raises(NotFound):
        log_time(session, job_id=job.id, technician_id=uuid4(), started_at=T0,
                 ended_at=T0 + timedelta(hours=1))


def test_time_entry_round_trip(session, a, job):
    log_time(session, job_id=job.id, technician_id=a.tech.id, started_at=T0,
             ended_at=T0 + timedelta(minutes=90), note="Diagnosis")
    session.expire_all()
    entry = session.scalars(select(TimeEntry).where(TimeEntry.job_id == job.id)).one()
    assert entry.hourly_rate_cents == 6_000
    assert entry.labor_cost_cents == 9_000


# --- sending alerts

def test_alerts_go_to_owners_once(session, a, job):
    result = submit_expense(session, job_id=job.id, submitted_by_user_id=a.owner.id, amount_cents=85_000)
    notifier = FakeNotifier()
    send_pending_alerts(session, notifier)

    mine = [s for s in notifier.sent if s[1].id == result.alert.id]
    assert len(mine) == 1
    to, alert, sent_job = mine[0]
    assert [u.email for u in to] == [a.owner.email]
    assert sent_job.id == job.id
    assert alert.sent_at is not None

    again = FakeNotifier()
    send_pending_alerts(session, again)
    assert not [s for s in again.sent if s[1].id == result.alert.id]


def test_failed_send_is_retried_later(session, a, job):
    result = submit_expense(session, job_id=job.id, submitted_by_user_id=a.owner.id, amount_cents=85_000)
    send_pending_alerts(session, FakeNotifier(fail=True))
    session.expire_all()
    assert session.get(BudgetAlert, result.alert.id).sent_at is None

    notifier = FakeNotifier()
    send_pending_alerts(session, notifier)
    assert [s for s in notifier.sent if s[1].id == result.alert.id]


# --- database backstops

def test_database_rejects_time_entry_over_24_hours(session, a, job):
    with pytest.raises(IntegrityError, match="ck_time_entries_at_most_24_hours"):
        session.execute(text(
            "INSERT INTO time_entries (id, company_id, job_id, technician_id, started_at, ended_at, "
            "hourly_rate_cents, created_at) VALUES (gen_random_uuid(), :c, :j, :t, now(), "
            "now() + interval '25 hours', 100, now())"
        ), {"c": a.company.id, "j": job.id, "t": a.tech.id})


def test_time_entry_cannot_use_another_companys_tech(session, a, b, job):
    entry = job.log_time(a.tech, T0, T0 + timedelta(hours=1))
    entry.technician_id = b.tech.id  # bypassing the domain on purpose
    session.add(entry)
    with pytest.raises(IntegrityError, match="fk_time_entries_technician_same_company"):
        session.flush()


def test_database_rejects_non_alert_level(session, a, job):
    session.add(BudgetAlert(a.company.id, job.id, BudgetLevel.OK, 100_000, 0))
    with pytest.raises(IntegrityError, match="ck_budget_alerts_alertable_level"):
        session.flush()


# --- visibility

@pytest.fixture
def jobs_ab(session, a, b):
    """Company A: one job for its tech, one unassigned. Company B: one job for its tech."""
    mine = make_job(a)
    unassigned = make_job(a, technician_id=None)
    theirs = make_job(b)
    session.add_all([mine, unassigned, theirs])
    session.flush()
    return mine, unassigned, theirs


@pytest.mark.parametrize("who", ["owner", "dispatcher"])
def test_office_sees_all_company_jobs(session, a, jobs_ab, who):
    mine, unassigned, theirs = jobs_ab
    user = a.owner if who == "owner" else User(company_id=a.company.id,
                                              email=f"d-{uuid4()}@example.com", role="dispatcher")
    session.add(user)
    session.flush()
    ids = {j.id for j in visible_jobs(session, user)}
    assert {mine.id, unassigned.id} <= ids
    assert theirs.id not in ids


def test_tech_sees_only_assigned_jobs(session, a, jobs_ab):
    mine, unassigned, theirs = jobs_ab
    assert [j.id for j in visible_jobs(session, tech_user(session, a))] == [mine.id]


def test_visible_job_hides_what_you_cannot_see(session, a, b, jobs_ab):
    mine, unassigned, theirs = jobs_ab
    tech = tech_user(session, a)
    assert visible_job(session, tech, mine.id).id == mine.id
    assert visible_job(session, tech, unassigned.id) is None
    assert visible_job(session, tech, theirs.id) is None
    assert visible_job(session, b.owner, mine.id) is None


def test_tech_sees_only_own_expenses(session, a, jobs_ab):
    mine = jobs_ab[0]
    tech = tech_user(session, a)
    own = mine.add_expense(a.company, tech, 1_000)
    owners = mine.add_expense(a.company, a.owner, 2_000)
    session.add_all([own, owners])
    session.flush()

    assert [e.id for e in visible_expenses(session, tech, mine.id)] == [own.id]
    assert {e.id for e in visible_expenses(session, a.owner, mine.id)} == {own.id, owners.id}


def test_other_company_sees_no_expenses(session, a, b, jobs_ab):
    mine = jobs_ab[0]
    session.add(mine.add_expense(a.company, a.owner, 1_000))
    session.flush()
    assert visible_expenses(session, b.owner, mine.id) == []
