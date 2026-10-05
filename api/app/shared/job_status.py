"""The job status flow. This table is the single source of truth for which moves are legal.

Requested -> Scheduled -> Dispatched -> EnRoute -> InProgress -> Completed -> Invoiced -> Paid
Cancelled is reachable from anything before Completed.
Dispatched -> Scheduled is allowed so a dispatcher can pull a job back (reschedule).
"""
from enum import Enum


class JobStatus(str, Enum):
    REQUESTED = "requested"
    SCHEDULED = "scheduled"
    DISPATCHED = "dispatched"
    EN_ROUTE = "en_route"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INVOICED = "invoiced"
    PAID = "paid"
    CANCELLED = "cancelled"


S = JobStatus

ALLOWED: dict[JobStatus, frozenset[JobStatus]] = {
    S.REQUESTED:   frozenset({S.SCHEDULED, S.CANCELLED}),
    S.SCHEDULED:   frozenset({S.DISPATCHED, S.CANCELLED}),
    S.DISPATCHED:  frozenset({S.EN_ROUTE, S.SCHEDULED, S.CANCELLED}),
    S.EN_ROUTE:    frozenset({S.IN_PROGRESS, S.CANCELLED}),
    S.IN_PROGRESS: frozenset({S.COMPLETED, S.CANCELLED}),
    S.COMPLETED:   frozenset({S.INVOICED}),
    S.INVOICED:    frozenset({S.PAID}),
    S.PAID:        frozenset(),
    S.CANCELLED:   frozenset(),
}

TERMINAL = frozenset(s for s, targets in ALLOWED.items() if not targets)


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    return target in ALLOWED[current]
