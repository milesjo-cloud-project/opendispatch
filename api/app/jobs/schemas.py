"""Request and response bodies for jobs, their history, files and tracking links."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.company.schemas import CustomerCreate
from app.shared.job_status import JobStatus
from app.shared.schemas import Cents, Out, Text200


class JobCreate(BaseModel):
    """Send `customer_id` for an existing customer, or `new_customer` to create one in the
    same request. `schedule: true` puts the job straight on the schedule (it needs a start).
    Either everything is saved or nothing is."""
    customer_id: UUID | None = None
    new_customer: CustomerCreate | None = None
    title: str = Text200()
    description: str | None = Field(default=None, max_length=10_000)
    technician_id: UUID | None = None
    scheduled_start: datetime | None = None
    quoted_amount_cents: int | None = Cents(default=None)
    schedule: bool = False

    @model_validator(mode="after")
    def _one_customer(self):
        if (self.customer_id is None) == (self.new_customer is None):
            raise ValueError("Send either customer_id or new_customer")
        return self


class JobUpdate(BaseModel):
    """Only the fields you send are changed. Send null to clear technician, start or quote."""
    title: str | None = Text200(default=None)
    description: str | None = Field(default=None, max_length=10_000)
    technician_id: UUID | None = None
    scheduled_start: datetime | None = None
    quoted_amount_cents: int | None = Cents(default=None)


class JobOut(Out):
    id: UUID
    customer_id: UUID
    technician_id: UUID | None
    title: str
    description: str | None
    status: JobStatus
    scheduled_start: datetime | None
    quoted_amount_cents: int | None  # office only; None for techs
    created_at: datetime
    customer_name: str | None = None
    customer_phone: str | None = None


class StatusChangeIn(BaseModel):
    status: JobStatus
    note: str | None = Field(default=None, max_length=2000)


class JobEventOut(Out):
    id: UUID
    from_status: JobStatus | None
    to_status: JobStatus
    actor_user_id: UUID | None
    note: str | None
    occurred_at: datetime


class TrackingLinkOut(BaseModel):
    path: str
    expires_at: datetime


class CustomerTrackingOut(BaseModel):
    title: str
    status: JobStatus
    scheduled_start: datetime | None
    last_updated: datetime | None


class JobAttachmentOut(Out):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
