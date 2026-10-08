"""The launch waitlist: people who want OpenDispatch before it ships, in Winter 2027.

This is the only feature in the app that isn't about a contractor's own work, and the only
one with no company_id. A signup belongs to whoever runs *this* server, not to a tenant:
the person signing up has no company here yet, and that is the whole point of the list.
So nothing in `app/shared/access.py` applies, the rows are never tenant-scoped, and the
office screens never see them. Reading the list needs WAITLIST_ADMIN_TOKEN (see routes.py).

A signup is just a message, like a booking request: it creates no company and no account,
and nothing here can turn into one. Spots are handed out in order and never reused,
because the founding price is promised to the first FOUNDING_SPOTS people on the list.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from app.shared.errors import DomainRuleViolation

# How many people get the founding price. Spot 101 onward is the general list.
FOUNDING_SPOTS = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PlanInterest(str, Enum):
    """Which of the launch offers brought them in. Not a commitment to buy."""

    HOSTED_MONTHLY = "hosted_monthly"
    ANNUAL = "annual"
    PERPETUAL = "perpetual"  # the one-time licence to the 1.x line
    SELF_HOSTED = "self_hosted"  # the free tier; still worth knowing about
    UNDECIDED = "undecided"


@dataclass(eq=False)
class WaitlistSignup:
    """One person waiting for launch. `spot` is assigned by the service, under a lock,
    so two people signing up at the same moment can't be given the same number."""

    email: str
    spot: int
    name: str | None = None
    company: str | None = None
    trade: str | None = None
    crew_size: str | None = None
    plan: PlanInterest = PlanInterest.UNDECIDED
    current_tool: str | None = None  # what they dispatch with today, in their words
    region: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        # Stored lower-cased: the unique index is on lower(email), and a waitlist that holds
        # Pat@x.com and pat@x.com as two people emails the same person twice at launch.
        self.email = (self.email or "").strip().lower()
        for text_field in ("name", "company", "trade", "crew_size", "current_tool", "region"):
            setattr(self, text_field, (getattr(self, text_field) or "").strip() or None)
        if "@" not in self.email or self.email.startswith("@") or self.email.endswith("@"):
            raise DomainRuleViolation("Please give an email address we can reach you at")
        if self.spot < 1:
            raise DomainRuleViolation("A waitlist spot starts at 1")

    @property
    def is_founding(self) -> bool:
        """Whether this spot still gets the founding price."""
        return self.spot <= FOUNDING_SPOTS
