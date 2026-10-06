"""Request and response bodies for sign-up, login, sessions and password reset."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.models import UserRole
from app.shared.schemas import Email, Out, Password, Text200


class SignupIn(BaseModel):
    company_name: str = Text200()
    email: str = Email()
    password: str = Password()
    phone: str | None = Field(default=None, max_length=32)


class SignupStatusOut(BaseModel):
    open: bool


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Password()


class UserOut(Out):
    id: UUID
    company_id: UUID
    email: str
    role: UserRole
    phone: str | None
    disabled_at: datetime | None = None  # set = can't sign in


class MeOut(UserOut):
    technician_id: UUID | None


class TokenOut(BaseModel):
    token: str
    expires_at: datetime
    user: MeOut


class MeUpdate(BaseModel):
    phone: str | None = Field(max_length=32)


class ResetRequestIn(BaseModel):
    email: str = Field(max_length=320)


class ResetConfirmIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    new_password: str = Password()


class PasswordChangeIn(BaseModel):
    current_password: str = Password()
    new_password: str = Password()
