"""Keeping technicians' calendars in step with the schedule, reliably.

Calendar writes deliberately don't happen in the request that caused them:

* a provider that's slow or down would make saving a job fail, and dispatching can't
  depend on an external calendar being up;
* a write that went out just before the transaction rolled back would put an event on a
  technician's calendar for a job that doesn't exist.

So routes call mark_dirty() in the same transaction as the edit, and sync_pending() does
the writing afterwards — from a background task once the response is out, and from
app/outbox/worker.py on a timer, which is what makes a failed write actually get retried
when nobody is using the app. The queue, the retry policy and the draining loop live in
app/shared/outbox.py.

An outbox row carries no payload. It says only "this job's calendar event no longer
matches the job"; the event is rebuilt from the job when it's sent. That means five edits
in a minute collapse into one write, a retry always sends the current state instead of a
stale snapshot, and there's no create/update/cancel ordering to get wrong: the sync looks
at what the job wants and what the provider has, and closes the gap.
"""
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.calendar.domain import DEFAULT_DURATION, CalendarEvent, EventGone, event_for, wants_event
from app.config import settings
from app.db.tables import calendar_outbox, job_calendar_events
from app.jobs import links
from app.shared import outbox
from app.shared.models import Customer, Job, Technician, User
from app.shared.ports import CalendarPort

log = logging.getLogger("opendispatch.calendar")

# How many tries, how long between them, and how much of the provider's complaint is
# kept: app/shared/outbox.py.
# How far back resync_technician() reaches: today's work counts, last month's doesn't.
RESYNC_WINDOW = timedelta(days=1)

_now = outbox.now_utc


@dataclass(frozen=True)
class EventOptions:
    """How to fill in an event. Kept out of domain.py so that stays free of configuration."""
    base_url: str = ""
    link_key: bytes | None = None  # None = technician job links are turned off
    link_ttl: timedelta = timedelta(hours=72)
    duration: timedelta = DEFAULT_DURATION


def event_options() -> EventOptions:
    return EventOptions(
        base_url=settings.app_base_url,
        link_key=settings.job_link_key,
        link_ttl=timedelta(hours=settings.job_link_ttl_hours),
        duration=timedelta(minutes=settings.default_job_minutes),
    )


def mark_dirty(session: Session, job: Job, *, now: datetime | None = None) -> None:
    """Queue this job's calendar event to be rewritten. Call it in the job's transaction.

    A job already waiting keeps its one row, and its backoff is reset: a fresh edit
    deserves a fresh try rather than the tail of an old provider outage.
    """
    outbox.queue(session, calendar_outbox, key=calendar_outbox.c.job_id,
                 company_id=job.company_id, job_id=job.id, now=now)


def invitee(session: Session, job: Job) -> User | None:
    """The account the invite goes to, or None when the job has nobody to invite.

    Disabling someone (they left, or their account was misused) takes the job off their
    calendar, along with the customer's address and phone number. Merely taking them off
    the schedule does not: the jobs already assigned to them are still theirs to finish,
    and shared.access lets them open those jobs, so their event stays put.
    """
    if job.technician_id is None:
        return None
    technician = session.get(Technician, job.technician_id)
    if technician is None or technician.company_id != job.company_id:
        return None
    user = session.get(User, technician.user_id)
    if user is None or user.is_disabled:
        return None
    return user


def _event_for_job(session: Session, job: Job, tech_user: User, options: EventOptions) -> CalendarEvent:
    """Build the event, including the technician's signed link."""
    customer = session.get(Customer, job.customer_id)
    if customer is not None and customer.company_id != job.company_id:
        customer = None

    link = None
    if options.link_key is not None:
        path, _ = links.link_for_job(job, key=options.link_key, ttl=options.link_ttl)
        link = f"{options.base_url.rstrip('/')}{path}"
    return event_for(job, customer, tech_user.email, link=link, duration=options.duration)


def _remember(session: Session, job: Job, external_id: str, now: datetime) -> None:
    session.execute(
        insert(job_calendar_events)
        .values(job_id=job.id, company_id=job.company_id, external_id=external_id,
                created_at=now, updated_at=now)
        .on_conflict_do_update(index_elements=[job_calendar_events.c.job_id],
                               set_={"external_id": external_id, "updated_at": now})
    )


def _forget(session: Session, job_id: UUID) -> None:
    session.execute(delete(job_calendar_events).where(job_calendar_events.c.job_id == job_id))


def sync_job(session: Session, calendar: CalendarPort, job_id: UUID, options: EventOptions) -> None:
    """Make the provider match the job: create, update, cancel, or do nothing.

    Idempotent on purpose. Running it twice is how retries work, and running it on a job
    that's already right costs one update and changes nothing.
    """
    job = session.get(Job, job_id)
    existing = session.execute(
        select(job_calendar_events.c.external_id).where(job_calendar_events.c.job_id == job_id)
    ).scalar_one_or_none()

    tech_user = invitee(session, job) if job is not None else None
    if job is None or not wants_event(job) or tech_user is None:
        if existing is not None:
            calendar.cancel_event(existing)
            _forget(session, job_id)
        return

    event = _event_for_job(session, job, tech_user, options)
    external_id = existing
    if external_id is not None:
        try:
            calendar.update_event(external_id, event)
        except EventGone:
            # Somebody deleted it at the provider. Make a new one rather than retrying
            # a call that can never succeed.
            log.warning("Calendar event for job %s is gone; making a new one", job_id)
            external_id = None
    if external_id is None:
        external_id = calendar.create_event(event)
    _remember(session, job, external_id, _now())


def resync_technician(session: Session, user: User, *, now: datetime | None = None) -> int:
    """Queue this person's current and upcoming jobs for a calendar write. Returns how many.

    For when something other than the job changed what their calendar should hold:
    disabling the account takes those jobs off their calendar, enabling it puts them back.
    Only today's work and later, deliberately — recreating events for jobs they finished
    months ago would be a pile of provider calls for nobody's benefit, and a past event
    does no harm where it is.
    """
    now = now or _now()
    jobs = session.scalars(
        select(Job)
        .join(Technician, (Technician.id == Job.technician_id)
              & (Technician.company_id == Job.company_id))
        .where(Technician.user_id == user.id,
               Job.scheduled_start.is_not(None),
               Job.scheduled_start > now - RESYNC_WINDOW)
    ).all()
    for job in jobs:
        mark_dirty(session, job, now=now)
    return len(jobs)


def sync_pending(
    session: Session,
    calendar: CalendarPort,
    *,
    limit: int = 50,
    now: datetime | None = None,
    options: EventOptions | None = None,
) -> int:
    """Do the calendar writes that are due. Returns how many jobs were brought up to date.

    Call it after the job's transaction has committed. The retries, the backoff and the
    locking are app/shared/outbox.py; what's here is what a calendar write *is*. The
    caller commits.
    """
    event_opts = options or event_options()

    def send(row: Mapping[str, Any]) -> None:
        sync_job(session, calendar, row["job_id"], event_opts)

    return outbox.drain(session, calendar_outbox, send,
                        what="calendar sync", limit=limit, now=now)
