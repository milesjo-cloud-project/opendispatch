"""Use cases for recording spend on a job. The API calls these; they call the domain.

Each one locks the job row, computes the budget before and after, saves the new spend,
and records a BudgetAlert in the same transaction if a threshold was crossed.
The caller commits, then calls send_pending_alerts() so nothing is sent for spend
that rolled back.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.adapters.db.tables import budget_alerts
from app.domain.budget import BudgetAlert, JobBudget, job_budget
from app.domain.entities import Company, Expense, Job, Technician, TimeEntry, User, UserRole
from app.ports.notifications import NotificationPort

log = logging.getLogger("opendispatch.spend")


class NotFound(LookupError):
    pass


@dataclass
class SpendResult:
    item: Expense | TimeEntry
    budget: JobBudget
    alert: BudgetAlert | None


def _get(session: Session, cls, id_: UUID, **kw):
    obj = session.get(cls, id_, **kw)
    if obj is None:
        raise NotFound(f"{cls.__name__} {id_} not found")
    return obj


def _current_budget(session: Session, job: Job) -> JobBudget:
    expenses = session.scalars(select(Expense).where(Expense.job_id == job.id))
    entries = session.scalars(select(TimeEntry).where(TimeEntry.job_id == job.id))
    return job_budget(job, expenses, entries)


def _lock_job(session: Session, job_id: UUID) -> Job:
    # Serializes spend on one job, so two expenses at once can't both miss a threshold.
    return _get(session, Job, job_id, with_for_update=True, populate_existing=True)


def _record(session: Session, job: Job, before: JobBudget, item) -> SpendResult:
    session.add(item)
    after = _current_budget(session, job)  # autoflush includes the new item
    alert = BudgetAlert.check(job, before, after)
    if alert is not None:
        inserted = session.execute(
            insert(budget_alerts)
            .values(id=alert.id, company_id=alert.company_id, job_id=alert.job_id,
                    level=alert.level.value, quoted_cents=alert.quoted_cents,
                    spent_cents=alert.spent_cents, created_at=alert.created_at)
            .on_conflict_do_nothing(constraint="uq_budget_alerts_job_id_level")
            .returning(budget_alerts.c.id)
        ).first()
        if inserted is None:
            alert = None  # this job already had that alert
    session.flush()
    return SpendResult(item, after, alert)


def submit_expense(
    session: Session,
    *,
    job_id: UUID,
    submitted_by_user_id: UUID,
    amount_cents: int,
    vendor: str | None = None,
    description: str | None = None,
    spent_on: date | None = None,
) -> SpendResult:
    job = _lock_job(session, job_id)
    company = _get(session, Company, job.company_id)
    user = _get(session, User, submitted_by_user_id)
    before = _current_budget(session, job)
    expense = job.add_expense(company, user, amount_cents, vendor, description, spent_on)
    return _record(session, job, before, expense)


def log_time(
    session: Session,
    *,
    job_id: UUID,
    technician_id: UUID,
    started_at: datetime,
    ended_at: datetime,
    note: str | None = None,
) -> SpendResult:
    job = _lock_job(session, job_id)
    technician = _get(session, Technician, technician_id)
    before = _current_budget(session, job)
    entry = job.log_time(technician, started_at, ended_at, note)
    return _record(session, job, before, entry)


def send_pending_alerts(session: Session, notifier: NotificationPort, limit: int = 100) -> int:
    """Send unsent budget alerts to each company's owners. Returns how many went out.

    Call after committing the spend. SKIP LOCKED lets two workers run this at once
    without sending the same alert twice. A failed send stays unsent for the next run.
    The caller commits afterwards to save sent_at.
    """
    pending = session.scalars(
        select(BudgetAlert)
        .where(BudgetAlert.sent_at.is_(None))
        .order_by(BudgetAlert.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    sent = 0
    for alert in pending:
        owners = session.scalars(
            select(User.email).where(User.company_id == alert.company_id, User.role == UserRole.OWNER)
        ).all()
        if not owners:
            log.warning("Budget alert %s has no owner to go to; will retry", alert.id)
            continue
        job = session.get(Job, alert.job_id)
        try:
            notifier.send_budget_alert(list(owners), alert, job)
        except Exception:
            log.exception("Budget alert %s failed to send; will retry", alert.id)
            continue
        alert.sent_at = datetime.now(timezone.utc)
        sent += 1
    session.flush()
    return sent
