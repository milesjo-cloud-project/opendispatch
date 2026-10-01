"""SQLAlchemy persistence operations for jobs and their status history."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.access import sees_all_jobs
from app.domain.entities import Customer, Job, JobEvent, Technician, User


class JobRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, job: Job) -> Job:
        self.session.add(job)
        return job

    def add_event(self, event: JobEvent) -> JobEvent:
        self.session.add(event)
        return event

    def get_visible(self, user: User, job_id: UUID) -> Job | None:
        stmt = select(Job).where(Job.company_id == user.company_id, Job.id == job_id)
        if not sees_all_jobs(user):
            stmt = stmt.join(
                Technician,
                (Technician.id == Job.technician_id) & (Technician.company_id == Job.company_id),
            ).where(Technician.user_id == user.id)
        return self.session.scalars(stmt).one_or_none()

    def list_visible(self, user: User) -> list[Job]:
        stmt = select(Job).where(Job.company_id == user.company_id)
        if not sees_all_jobs(user):
            stmt = stmt.join(
                Technician,
                (Technician.id == Job.technician_id) & (Technician.company_id == Job.company_id),
            ).where(Technician.user_id == user.id)
        return list(self.session.scalars(stmt.order_by(Job.created_at, Job.id)))


class CustomerRepository:
    """Tenant-safe customer lookup used when validating a new job."""

    def __init__(self, session: Session):
        self.session = session

    def get_for_company(self, customer_id: UUID, company_id: UUID):
        customer = self.session.get(Customer, customer_id)
        return customer if customer is not None and customer.company_id == company_id else None
