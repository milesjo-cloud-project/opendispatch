"""The outbox pattern, shared by everything that writes to somebody else's service.

A feature that has to tell an outside provider something (put this job on a calendar,
add this signup to a spreadsheet) must not do it inside the request that caused it: a
provider that's slow or down would make saving fail, and a write that went out just
before the transaction rolled back would leave the provider holding something that never
happened here.

So the route calls queue() in the same transaction as the edit, and drain() does the
writing afterwards — from a background task once the response is out, and from
app/outbox/worker.py on a timer, which is what makes a failed write actually get retried
when nobody is using the app.

A row carries no payload. It names the thing that changed, and the current state is read
back when the write goes out. That means repeated edits collapse into one call, a retry
sends today's state instead of a stale snapshot, and there's no ordering to get wrong.

Each feature keeps its own table (calendar_outbox, waitlist_outbox) so the columns can
say what they're about; the policy and the loop live here.
"""
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

log = logging.getLogger("opendispatch.outbox")

# Tries before a row is left alone. With the backoff below that spreads over about 20
# hours, which is the point: a refresh token that expired overnight, or a provider outage
# that started after everyone went home, is fixed in the morning and the write still lands.
# Giving up in an hour would mean a job quietly never reaching the technician's calendar.
MAX_ATTEMPTS = 12
FIRST_RETRY = timedelta(seconds=30)
LONGEST_RETRY = timedelta(hours=6)
# Enough of the provider's complaint to act on, without filling the table.
MAX_ERROR_CHARS = 1000


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def retry_after(attempts: int) -> timedelta:
    """Doubling backoff: 30s, 1m, 2m, ... capped at LONGEST_RETRY."""
    return min(FIRST_RETRY * 2 ** (attempts - 1), LONGEST_RETRY)


def queue(session: Session, table: Table, *, key: Column,
          now: datetime | None = None, **values: Any) -> None:
    """Queue a write. Call it inside the transaction that made the change.

    Something already waiting keeps its one row, and its backoff is reset: a fresh edit
    deserves a fresh try rather than the tail of an old provider outage. `key` is the
    column a pending row is unique on (a job, a signup).
    """
    now = now or now_utc()
    session.execute(
        insert(table)
        .values(id=uuid4(), attempts=0, next_attempt_at=now, created_at=now, **values)
        .on_conflict_do_update(
            index_elements=[key],
            index_where=table.c.sent_at.is_(None),
            set_={"attempts": 0, "next_attempt_at": now, "last_error": None},
        )
    )


def drain(session: Session, table: Table, send: Callable[[Mapping[str, Any]], None], *,
          what: str, limit: int = 50, now: datetime | None = None) -> int:
    """Do the writes that are due, and return how many went out.

    Call it once the transaction that queued them has committed. SKIP LOCKED lets the
    API's background task and the worker run at the same time without sending the same
    write twice. A failed write stays queued with its next try pushed out, so the row is
    also the record of what went wrong (`last_error`). The caller commits.
    """
    now = now or now_utc()
    due = session.execute(
        select(table)
        .where(table.c.sent_at.is_(None),
               table.c.next_attempt_at <= now,
               table.c.attempts < MAX_ATTEMPTS)
        .order_by(table.c.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).mappings().all()

    sent = 0
    for row in due:
        try:
            # Its own savepoint, so one failure rolls back only its own work and leaves
            # the transaction usable for the rest of the batch.
            with session.begin_nested():
                send(row)
                session.execute(table.update().where(table.c.id == row["id"])
                                .values(sent_at=now, last_error=None))
            sent += 1
        except Exception as exc:
            attempts = row["attempts"] + 1
            log.exception("%s %s failed (attempt %d)", what, row["id"], attempts)
            if attempts >= MAX_ATTEMPTS:
                log.error("Giving up on %s %s after %d attempts; the row stays in %s "
                          "with last_error", what, row["id"], attempts, table.name)
            session.execute(table.update().where(table.c.id == row["id"])
                            .values(attempts=attempts,
                                    next_attempt_at=now + retry_after(attempts),
                                    last_error=str(exc)[:MAX_ERROR_CHARS]))
    session.flush()
    return sent
