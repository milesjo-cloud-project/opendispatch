"""Signed, expiring links that open one job for one technician, with no login.

This is how a job reaches a worker who hasn't installed anything: the link goes in the
calendar event (app/calendar/), and tapping it on a phone shows the address, the contact
and what the work is. Nothing about the link is stored, so there's no table to leak and
nothing to clean up — the signature is what makes it real, and a changed JOB_LINK_SECRET
invalidates every link at once.

The cost of storing nothing is that one link can't be revoked on its own, so three things
keep what a leaked link is worth small:

* it expires (`expiry_for`);
* it names the technician, so reassigning the job kills the old link;
* it opens one job, read-only, and never shows the quote or anything about other jobs.

Customer tracking links (jobs/tracking.py) work the other way round — random tokens with
only their hash in a table — because a customer's link lives for 90 days and the office
needs to be able to replace it. Pick that shape when revoking matters more than storing
nothing. Both kinds are served from tracking.py; this module is just the tokens.
"""
import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.shared.models import Job

# Bumped if the payload ever changes shape, so old tokens are refused instead of misread.
VERSION = "1"


class InvalidJobLink(Exception):
    """Unknown, tampered with, or expired. Deliberately one error for all of them."""


@dataclass(frozen=True)
class JobLink:
    """What a valid token says. Whether the job still matches is the caller's to check."""
    job_id: UUID
    technician_id: UUID
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _signature(payload: str, key: bytes) -> str:
    digest = hmac.new(key, payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def expiry_for(scheduled_start: datetime | None, ttl: timedelta, now: datetime | None = None) -> datetime:
    """When a link made now should stop working.

    The clock starts at the job's scheduled time, not now: a job three weeks out needs a
    link that still works on the day, and one scheduled for this morning shouldn't stay
    openable for weeks afterwards.
    """
    now = now or _now()
    return max(now, scheduled_start or now) + ttl


def mint(job_id: UUID, technician_id: UUID, *, key: bytes, expires_at: datetime) -> str:
    """The token for `job_id`, openable by whoever holds it until `expires_at`."""
    payload = f"{VERSION}.{job_id.hex}.{technician_id.hex}.{int(expires_at.timestamp())}"
    return f"{payload}.{_signature(payload, key)}"


def verify(token: str, *, key: bytes, now: datetime | None = None) -> JobLink:
    """Check the signature and the expiry. Raises InvalidJobLink; never touches the database."""
    payload, _, signature = token.rpartition(".")
    if not signature or not payload:
        raise InvalidJobLink()
    # Compared as bytes: compare_digest raises TypeError on a str holding non-ASCII, and a
    # URL can hold anything. Checked before anything is parsed, so unsigned input never
    # gets a say in what happens next.
    if not hmac.compare_digest(signature.encode("utf-8", "surrogatepass"),
                               _signature(payload, key).encode()):
        raise InvalidJobLink()
    version, _, rest = payload.partition(".")
    if version != VERSION:
        raise InvalidJobLink()
    try:
        job_hex, technician_hex, expires = rest.split(".")
        expires_at = datetime.fromtimestamp(int(expires), timezone.utc)
        link = JobLink(UUID(hex=job_hex), UUID(hex=technician_hex), expires_at)
    except (ValueError, OverflowError, OSError):
        raise InvalidJobLink() from None  # signed by us, but not a token we would ever have made
    if link.expires_at <= (now or _now()):
        raise InvalidJobLink()
    return link


def path_for(token: str) -> str:
    """Where the web app opens a token. Short, because it has to fit on a phone screen."""
    return f"/j/{token}"


def link_for_job(job: Job, *, key: bytes, ttl: timedelta,
                 now: datetime | None = None) -> tuple[str, datetime]:
    """A link for the job's assigned technician: the path, and when it stops working."""
    if job.technician_id is None:
        raise ValueError("A job link names a technician; this job has none")
    expires_at = expiry_for(job.scheduled_start, ttl, now)
    return path_for(mint(job.id, job.technician_id, key=key, expires_at=expires_at)), expires_at
