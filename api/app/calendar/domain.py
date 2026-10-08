"""What a job looks like on a calendar, and whether it belongs on one at all.

No database and no HTTP here: service.py loads the rows, this turns them into the event,
and the adapters behind CalendarPort decide how to write it.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.shared.job_status import JobStatus
from app.shared.models import Customer, Job

# A job has a start time but no end yet, so an event has to assume a length.
DEFAULT_DURATION = timedelta(minutes=120)

# Calendar events are rebuilt from the job on every sync, so anything typed into them at
# the provider is lost. Say so where the person doing the typing will see it.
MANAGED_NOTE = "Created by OpenDispatch. Changes made here are replaced when the job is edited."


class EventGone(Exception):
    """The provider says this event no longer exists (somebody deleted it by hand).

    Raised by update_event so the sync can make a new one instead of retrying forever.
    """


@dataclass(frozen=True)
class CalendarEvent:
    """One job, ready for a calendar. Everything an adapter needs and nothing it doesn't."""
    job_id: UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    technician_email: str
    description: str | None = None
    location: str | None = None


# A requested job is still a draft (the web app files it under "Open shifts"), so it isn't
# anybody's commitment yet; cancelling takes a job back off again.
OFF_CALENDAR = frozenset({JobStatus.REQUESTED, JobStatus.CANCELLED})


def wants_event(job: Job) -> bool:
    """Whether this job should have an event right now.

    A job belongs on a calendar once somebody has to be somewhere at a time: it needs a
    technician, a start, and to be on the schedule rather than a draft. Completed,
    invoiced and paid jobs keep their event, because the work did happen.
    """
    return (job.technician_id is not None
            and job.scheduled_start is not None
            and job.status not in OFF_CALENDAR)


def describe(job: Job, customer: Customer | None, link: str | None = None) -> str:
    """The event body: who to call, where to go, what the work is, and the job link.

    Phone numbers and addresses are the point of this: a technician reading it on a phone
    outside the house shouldn't have to open anything else.
    """
    lines: list[str] = []
    if customer is not None:
        lines.append(customer.name)
        if customer.phone:
            lines.append(customer.phone)
        if customer.address:
            lines.append(customer.address)
    if job.description:
        if lines:
            lines.append("")
        lines.append(job.description)
    if link:
        lines += ["", f"Job details: {link}"]
    lines += ["", MANAGED_NOTE]
    return "\n".join(lines)


def event_for(
    job: Job,
    customer: Customer | None,
    technician_email: str,
    *,
    link: str | None = None,
    duration: timedelta = DEFAULT_DURATION,
) -> CalendarEvent:
    """Build the event for a job that wants_event() says belongs on a calendar."""
    if job.scheduled_start is None or job.technician_id is None:
        raise ValueError("A calendar event needs a scheduled start and a technician")
    title = job.title if customer is None else f"{job.title} — {customer.name}"
    return CalendarEvent(
        job_id=job.id,
        title=title,
        starts_at=job.scheduled_start,
        ends_at=job.scheduled_start + duration,
        technician_email=technician_email,
        description=describe(job, customer, link),
        location=customer.address if customer is not None else None,
    )
