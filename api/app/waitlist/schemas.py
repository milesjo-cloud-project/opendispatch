"""Request and response bodies for the launch waitlist."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.schemas import Email, Out
from app.waitlist.domain import PlanInterest


class WaitlistStatusOut(BaseModel):
    """What the public page needs before anyone types anything."""

    founding_spots: int
    spots_left: int
    launch: str  # e.g. "Winter 2027", shown as-is


class WaitlistJoinIn(BaseModel):
    """What a visitor sends from the public form. Checked again in waitlist/domain.py."""

    email: str = Email()
    name: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    trade: str | None = Field(default=None, max_length=100)
    crew_size: str | None = Field(default=None, max_length=40)
    plan: PlanInterest = PlanInterest.UNDECIDED
    current_tool: str | None = Field(default=None, max_length=200)
    region: str | None = Field(default=None, max_length=200)
    # Honeypot: the form hides this from people, so anything in it was typed by a bot
    website: str | None = Field(default=None, max_length=500)


class WaitlistJoinedOut(BaseModel):
    """No id: a signup can't be used to look anything up afterwards.

    `already_on_list` is true when this address had signed up before, so the page can say
    "you're already number 12" instead of pretending it just saved them again.
    """

    spot: int
    is_founding: bool
    already_on_list: bool
    spots_left: int


class WaitlistSignupOut(Out):
    """One row, for whoever runs the server. Never returned to a public caller."""

    id: UUID
    spot: int
    email: str
    name: str | None
    company: str | None
    trade: str | None
    crew_size: str | None
    plan: PlanInterest
    current_tool: str | None
    region: str | None
    created_at: datetime


class WaitlistReportOut(BaseModel):
    """The admin view: the list plus the few numbers worth watching before launch."""

    total: int
    spots_left: int
    last_24_hours: int
    by_plan: dict[str, int]
    signups: list[WaitlistSignupOut]
