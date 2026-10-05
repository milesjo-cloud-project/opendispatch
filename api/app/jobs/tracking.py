"""Short-lived, private customer tracking links. They reveal job progress only."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.tables import job_events, job_tracking_links, jobs
from app.jobs.schemas import CustomerTrackingOut, TrackingLinkOut
from app.shared.deps import Actor, get_session, office_actor
from app.shared.job_status import JobStatus
from app.shared.models import Job
from app.spend.service import NotFound

router = APIRouter(tags=["customer tracking"])


@router.post("/jobs/{job_id}/tracking-link", response_model=TrackingLinkOut, status_code=201)
def create_tracking_link(job_id: UUID, actor: Actor = Depends(office_actor), session: Session = Depends(get_session)):
    """Create or rotate an invoice tracking URL. Only invoiced jobs can be shared."""
    job = session.get(Job, job_id)
    if job is None or job.company_id != actor.user.company_id:
        raise NotFound(f"Job {job_id}")
    if job.status not in {JobStatus.INVOICED, JobStatus.PAID}:
        raise HTTPException(status.HTTP_409_CONFLICT, "A tracking link is available after invoicing")
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
