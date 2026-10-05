"""Read queries that apply the visibility rules in shared/access.py inside SQL,
so rows a user may not see are never loaded in the first place."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.repositories import JobRepository
from app.shared.access import sees_all_jobs
from app.shared.models import Expense, Job, User


def visible_jobs(session: Session, user: User) -> list[Job]:
    return JobRepository(session).list_visible(user)


def visible_job(session: Session, user: User, job_id) -> Job | None:
    """The job, or None if it doesn't exist OR the user may not see it (same answer on purpose)."""
    return JobRepository(session).get_visible(user, job_id)


def visible_expenses(session: Session, user: User, job_id) -> list[Expense]:
    """Office staff see every expense on the job; a tech sees only their own, on their own jobs."""
    if visible_job(session, user, job_id) is None:
        return []
    stmt = select(Expense).where(Expense.job_id == job_id, Expense.company_id == user.company_id)
    if not sees_all_jobs(user):
        stmt = stmt.where(Expense.submitted_by_user_id == user.id)
    return list(session.scalars(stmt.order_by(Expense.created_at, Expense.id)))
