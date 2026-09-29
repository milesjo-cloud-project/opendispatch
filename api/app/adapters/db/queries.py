"""Read queries that apply the visibility rules in domain/access.py inside SQL,
so rows a user may not see are never loaded in the first place."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.access import sees_all_jobs
from app.domain.entities import Expense, Job, Technician, User


def _visible_jobs_stmt(user: User):
    stmt = select(Job).where(Job.company_id == user.company_id)
    if not sees_all_jobs(user):
        stmt = stmt.join(
            Technician,
            (Technician.id == Job.technician_id) & (Technician.company_id == Job.company_id),
        ).where(Technician.user_id == user.id)
    return stmt


def visible_jobs(session: Session, user: User) -> list[Job]:
    return list(session.scalars(_visible_jobs_stmt(user).order_by(Job.created_at, Job.id)))


def visible_job(session: Session, user: User, job_id) -> Job | None:
    """The job, or None if it doesn't exist OR the user may not see it (same answer on purpose)."""
    return session.scalars(_visible_jobs_stmt(user).where(Job.id == job_id)).one_or_none()


def visible_expenses(session: Session, user: User, job_id) -> list[Expense]:
    """Office staff see every expense on the job; a tech sees only their own, on their own jobs."""
    if visible_job(session, user, job_id) is None:
        return []
    stmt = select(Expense).where(Expense.job_id == job_id, Expense.company_id == user.company_id)
    if not sees_all_jobs(user):
        stmt = stmt.where(Expense.submitted_by_user_id == user.id)
    return list(session.scalars(stmt.order_by(Expense.created_at, Expense.id)))
