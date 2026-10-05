"""Request and response bodies for company settings, the team and customers."""
from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.models import UserRole
from app.shared.schemas import Cents, Email, Out, Password, Text200


class CompanyOut(Out):
    id: UUID
    name: str
    expense_approval_limit_cents: int
    sms_alerts_enabled: bool
    booking_id: str | None = None  # None = online booking off


class CompanyUpdate(BaseModel):
    name: str | None = Text200(default=None)
    expense_approval_limit_cents: int | None = Cents(default=None)
    sms_alerts_enabled: bool | None = None


class TechnicianProfileIn(BaseModel):
    display_name: str = Text200()
    hourly_rate_cents: int | None = Cents(default=None)


class UserCreate(BaseModel):
    """`technician` also gives them a technician profile, in the same transaction."""
    email: str = Email()
    role: UserRole
    password: str = Password()
    phone: str | None = Field(default=None, max_length=32)
    technician: TechnicianProfileIn | None = None


class TechnicianCreate(BaseModel):
    user_id: UUID
    display_name: str = Text200()
    phone: str | None = Field(default=None, max_length=40)
    hourly_rate_cents: int | None = Cents(default=None)


class TechnicianUpdate(BaseModel):
    display_name: str | None = Text200(default=None)
    phone: str | None = Field(default=None, max_length=40)
    active: bool | None = None
    hourly_rate_cents: int | None = Cents(default=None)


class TechnicianOut(Out):
    id: UUID
    user_id: UUID
    display_name: str
    phone: str | None
    active: bool
    hourly_rate_cents: int | None  # owners only; None for everyone else


class CustomerCreate(BaseModel):
    name: str = Text200()
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    address: str | None = Field(default=None, max_length=2000)


class CustomerOut(Out):
    id: UUID
    name: str
    phone: str | None
    email: str | None
    address: str | None
