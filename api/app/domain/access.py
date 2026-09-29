"""Who can see what. Plain rules with no knowledge of how someone logged in.

Owners and dispatchers see every job in their company. Technicians see only the jobs
assigned to them, and the expenses and time on those jobs. Only owners and dispatchers
see money that isn't theirs: quotes, budgets, and other people's expenses.

The database side (only loading rows a user may see) lives in adapters/db/queries.py
and must agree with these rules; tests check both.
"""
from .entities import Expense, Job, Technician, User, UserRole

OFFICE_ROLES = frozenset({UserRole.OWNER, UserRole.DISPATCHER})


def sees_all_jobs(user: User) -> bool:
    return user.role in OFFICE_ROLES


def can_view_job(user: User, job: Job, technician: Technician | None = None) -> bool:
    """`technician` is the user's own technician profile, if they have one."""
    if user.company_id != job.company_id:
        return False
    if sees_all_jobs(user):
        return True
    return (
        technician is not None
        and technician.user_id == user.id
        and technician.company_id == user.company_id
        and job.technician_id == technician.id
    )


def can_view_budget(user: User, job: Job) -> bool:
    """The quote and budget-vs-actual. Techs don't see what the customer is paying."""
    return user.company_id == job.company_id and user.role in OFFICE_ROLES


def can_view_expense(
    user: User, expense: Expense, job: Job, technician: Technician | None = None
) -> bool:
    if expense.job_id != job.id or expense.company_id != user.company_id:
        return False
    if sees_all_jobs(user):
        return True
    return expense.submitted_by_user_id == user.id and can_view_job(user, job, technician)
