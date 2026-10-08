"""Keeping the launch spreadsheet in step with the waitlist table.

The database is where a signup lives; the spreadsheet is a copy, for the people deciding
what to build and who to email at launch. So this only ever writes outwards, and losing
the sheet loses nothing: queue_all() builds it again.

Signing up must not depend on Google being reachable — the whole point of the page is that
somebody fills it in once and never comes back — so the write goes through the outbox in
app/shared/outbox.py: routes queue it in the signup's transaction, and the write happens
after the response, or from app/outbox/worker.py when that fails.
"""
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tables import waitlist_outbox, waitlist_signups
from app.shared import outbox
from app.shared.ports import SpreadsheetPort
from app.waitlist.domain import WaitlistSignup
from app.waitlist.sheet import rows_for

log = logging.getLogger("opendispatch.waitlist")


def mark_dirty(session: Session, signup: WaitlistSignup, *, now: datetime | None = None) -> None:
    """Queue this signup to be written to the spreadsheet. Call it in its transaction."""
    outbox.queue(session, waitlist_outbox, key=waitlist_outbox.c.signup_id,
                 signup_id=signup.id, now=now)


def queue_all(session: Session, *, now: datetime | None = None) -> int:
    """Queue every signup, and return how many. For a spreadsheet that didn't exist when
    people were signing up, or one that was replaced: each row goes back where it was,
    because a signup's row number comes from its spot (waitlist/sheet.py)."""
    signups = list(session.scalars(select(WaitlistSignup).order_by(waitlist_signups.c.spot)))
    for signup in signups:
        mark_dirty(session, signup, now=now)
    return len(signups)


def sync_signup(session: Session, sheet: SpreadsheetPort, signup_id: UUID) -> None:
    """Write one signup's row (and the header). Safe to call twice; that's how retries work."""
    signup = session.get(WaitlistSignup, signup_id)
    if signup is None:
        # Deleted between queueing and sending. Nothing to write, and nothing to undo:
        # clearing a row already in the sheet is the owner's call, not ours.
        log.info("Waitlist signup %s is gone; nothing to write to the spreadsheet", signup_id)
        return
    sheet.write_rows(rows_for(signup))


def sync_pending(session: Session, sheet: SpreadsheetPort, *, limit: int = 50,
                 now: datetime | None = None) -> int:
    """Do the spreadsheet writes that are due. Returns how many went out. The caller commits."""
    def send(row: Mapping[str, Any]) -> None:
        sync_signup(session, sheet, row["signup_id"])

    return outbox.drain(session, waitlist_outbox, send,
                        what="waitlist spreadsheet write", limit=limit, now=now)
