"""Request and response bodies for online booking."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.booking.domain import BookingRequestStatus
from app.shared.schemas import Email, Out, Text200


class BookingLinkOut(BaseModel):
    booking_id: str
    path: str  # e.g. /book/AbC123xYz789, for the web app to put after its own address


class BookingPageOut(BaseModel):
    """All a stranger learns from a booking link: who they're booking with."""
    company_name: str


class BookingIn(BaseModel):
    """What a customer sends from the public form. Checked again in booking/domain.py."""
    name: str = Text200()
    title: str = Text200()
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Email(default=None)
    address: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=5000)
    preferred_time: str | None = Field(default=None, max_length=200)
    # Honeypot: the form hides this from people, so anything in it was typed by a bot
    website: str | None = Field(default=None, max_length=500)


class BookingReceivedOut(BaseModel):
    """No ids: a booking can't be used to look anything up afterwards."""
    company_name: str


class BookingRequestOut(Out):
    id: UUID
    name: str
    phone: str | None
    email: str | None
    address: str | None
    title: str
    description: str | None
    preferred_time: str | None
    status: BookingRequestStatus
    job_id: UUID | None
    created_at: datetime


class BookingAcceptIn(BaseModel):
    """An existing customer's id, or none to make a new customer from the request."""
    customer_id: UUID | None = None
