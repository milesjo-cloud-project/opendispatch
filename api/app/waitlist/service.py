"""Use cases for the launch waitlist. The API calls these; they call the domain. The caller commits.

Public: join the list, and read how many founding spots are left.
Whoever runs the server: read the list (routes.py checks the admin token first).
"""
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tables import waitlist_signups
from app.waitlist.domain import FOUNDING_SPOTS, PlanInterest, WaitlistSignup

# One key for the whole table, so spots are handed out one at a time. Any constant does;
# this is "waitlist" as a 32-bit int, kept here so nothing else picks the same number.
_SPOT_LOCK = 1_937_010_540


def join(session: Session, *, email: str, **fields) -> tuple[WaitlistSignup, bool]:
    """Put someone on the list and return them with whether they are new.

    Signing up twice is not an error: the same address gets its original spot back,
    unchanged. Someone who forgets they signed up should see the spot they already hold,
    not lose it, and a retried request (a double tap, a flaky phone) must not take two
    numbers. Anything they typed the second time is dropped, because the first answer is
    the one we have already acted on.
    """
    normalized = (email or "").strip().lower()
    existing = session.scalars(
        select(WaitlistSignup).where(func.lower(waitlist_signups.c.email) == normalized)
    ).one_or_none() if normalized else None
    if existing is not None:
        return existing, False

    # Taken before reading the highest spot, and held until the caller commits, so two
    # people signing up at once queue here instead of both being told they are number 12.
    session.execute(select(func.pg_advisory_xact_lock(_SPOT_LOCK)))
    taken = session.scalar(select(func.max(waitlist_signups.c.spot))) or 0
    signup = WaitlistSignup(email=normalized, spot=taken + 1, **fields)
    session.add(signup)
    session.flush()
    return signup, True


def spots_left(session: Session) -> int:
    """Founding spots still unclaimed, for the public page's counter."""
    return max(0, FOUNDING_SPOTS - (session.scalar(select(func.count()).select_from(waitlist_signups)) or 0))


def signups(session: Session, *, limit: int = 1000) -> list[WaitlistSignup]:
    """The whole list in the order people joined. Not tenant-scoped; see domain.py."""
    return list(session.scalars(
        select(WaitlistSignup).order_by(waitlist_signups.c.spot).limit(limit)
    ))


def counts_by_plan(session: Session) -> dict[str, int]:
    """How many people each offer brought in, for deciding what to build first."""
    rows = session.execute(
        select(waitlist_signups.c.plan, func.count())
        .group_by(waitlist_signups.c.plan)
    ).all()
    found = {plan: count for plan, count in rows}
    # Every plan appears, so a zero reads as zero rather than as a missing key.
    return {plan.value: found.get(plan.value, found.get(plan, 0)) for plan in PlanInterest}


def recent(session: Session, *, within: timedelta) -> int:
    """Signups in the last `within`, so the owner can see whether a post landed."""
    cutoff = func.now() - within
    return session.scalar(
        select(func.count()).select_from(waitlist_signups).where(waitlist_signups.c.created_at >= cutoff)
    ) or 0


def by_id(session: Session, signup_id: UUID) -> WaitlistSignup | None:
    return session.get(WaitlistSignup, signup_id)
