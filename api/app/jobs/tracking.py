"""Private links that open one job without a login, for the two people who aren't signed in.

The customer's tracking link shows job progress only, lives for 90 days, and is a random
token stored as a hash so the office can replace it. The technician's job link shows the
address and the contact so they can do the work, and is signed rather than stored
(jobs/links.py explains the trade-off). Neither ever shows money.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.tables import job_events, job_tracking_links, jobs
from app.jobs import links
from app.jobs.schemas import CustomerTrackingOut, JobLinkOut, TechnicianJobOut, TrackingLinkOut
from app.shared.deps import Actor, get_session, office_actor
from app.shared.job_status import JobStatus
from app.shared.models import Customer, Job, Technician, User
from app.spend.service import NotFound

router = APIRouter(tags=["customer tracking"])

# A draft has no time to share yet, and a cancelled job has nothing to follow. A link made
# earlier keeps working after a cancel, so the customer sees that it was cancelled.
NOT_SHAREABLE = {JobStatus.REQUESTED, JobStatus.CANCELLED}


@router.post("/jobs/{job_id}/tracking-link", response_model=TrackingLinkOut, status_code=201)
def create_tracking_link(job_id: UUID, actor: Actor = Depends(office_actor), session: Session = Depends(get_session)):
    """Create or replace the customer's tracking link, from Scheduled on."""
    job = session.get(Job, job_id)
    if job is None or job.company_id != actor.user.company_id:
        raise NotFound(f"Job {job_id}")
    if job.status in NOT_SHAREABLE:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "A tracking link is available once the job is scheduled, and not for cancelled jobs")
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    session.execute(delete(job_tracking_links).where(job_tracking_links.c.job_id == job.id))
    session.execute(job_tracking_links.insert().values(
        id=uuid4(), company_id=job.company_id, job_id=job.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=now + timedelta(days=90), created_at=now,
    ))
    session.commit()
    return TrackingLinkOut(path=f"/track/{token}", expires_at=now + timedelta(days=90))


@router.get("/public/tracking/{token}", response_model=CustomerTrackingOut)
def public_tracking(token: str, session: Session = Depends(get_session)):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = session.execute(
        select(jobs.c.title, jobs.c.status, jobs.c.scheduled_start,
               func.max(job_events.c.occurred_at).label("last_updated"))
        .join(job_tracking_links, job_tracking_links.c.job_id == jobs.c.id)
        .outerjoin(job_events, job_events.c.job_id == jobs.c.id)
        .where(job_tracking_links.c.token_hash == token_hash,
               job_tracking_links.c.revoked_at.is_(None),
               job_tracking_links.c.expires_at > datetime.now(timezone.utc))
        .group_by(jobs.c.id, jobs.c.title, jobs.c.status, jobs.c.scheduled_start)
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This tracking link is invalid or expired")
    return CustomerTrackingOut(title=row.title, status=row.status,
                               scheduled_start=row.scheduled_start, last_updated=row.last_updated)


# --- the technician's signed job link

TECH_LINK_TAGS = ["technician job links"]


@router.post("/jobs/{job_id}/job-link", response_model=JobLinkOut, status_code=201,
             tags=TECH_LINK_TAGS)
def create_job_link(job_id: UUID, actor: Actor = Depends(office_actor),
                    session: Session = Depends(get_session)):
    """A link to send the assigned technician by hand; the same one their calendar event carries.

    Making one doesn't invalidate the links already out there, because none of them are
    stored. They expire on their own.
    """
    key = settings.job_link_key
    if key is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Technician job links are turned off: JOB_LINK_SECRET isn't set")
    job = session.get(Job, job_id)
    if job is None or job.company_id != actor.user.company_id:
        raise NotFound(f"Job {job_id}")
    if job.technician_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Assign the job to a technician first; a job link is for one technician")
    path, expires_at = links.link_for_job(job, key=key,
                                          ttl=timedelta(hours=settings.job_link_ttl_hours))
    return JobLinkOut(path=path, expires_at=expires_at)


@router.get("/public/job-link/{token}", response_model=TechnicianJobOut, tags=TECH_LINK_TAGS)
def open_job_link(token: str, session: Session = Depends(get_session)):
    """What the technician's link shows. No login, so it says as little as it can.

    Every refusal is the same 404, whether the token is nonsense, expired, for a job
    that's gone, or for a job that is now somebody else's: a link that stopped working
    shouldn't say why, or confirm that the job exists.
    """
    gone = HTTPException(status.HTTP_404_NOT_FOUND, "This job link is invalid or has expired")
    key = settings.job_link_key
    if key is None:
        raise gone
    try:
        link = links.verify(token, key=key)
    except links.InvalidJobLink:
        raise gone from None

    job = session.get(Job, link.job_id)
    # Reassigning the job ends the old link, so a tech who's off the job can't still read it.
    if job is None or job.technician_id != link.technician_id:
        raise gone
    technician = session.get(Technician, link.technician_id)
    if technician is None or technician.company_id != job.company_id:
        raise gone
    # A disabled account is cut off everywhere, links included. Being taken off the
    # schedule is NOT: shared.access lets an inactive technician open the jobs already
    # assigned to them, so breaking their link would only stop them doing today's work.
    tech_user = session.get(User, technician.user_id)
    if tech_user is None or tech_user.is_disabled:
        raise gone

    customer = session.get(Customer, job.customer_id)
    if customer is not None and customer.company_id != job.company_id:
        customer = None
    return TechnicianJobOut(
        title=job.title, description=job.description, status=job.status,
        scheduled_start=job.scheduled_start, technician_name=technician.display_name,
        customer_name=customer.name if customer else None,
        customer_phone=customer.phone if customer else None,
        customer_address=customer.address if customer else None,
        expires_at=link.expires_at,
    )
