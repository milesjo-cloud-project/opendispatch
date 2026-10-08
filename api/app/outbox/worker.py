"""Drains every outbox on a timer: `python -m app.outbox.worker`.

The API already drains them in a background task after the request that queued the write,
which covers the normal case. This is what makes "it retries" true the rest of the time:
when Google is down for an hour, when the write that failed was the last request of the
day, or when a refresh token expired overnight.

One process for all of them on purpose. They share a retry policy (app/shared/outbox.py)
and the work is a handful of HTTP calls a day, so a second container would be a second
thing to deploy and watch for nothing. One replica is plenty -- SKIP LOCKED means more
than one is safe, not faster.
"""
import logging
import signal
import time
from types import FrameType

from app.calendar.service import sync_pending as sync_calendar
from app.config import settings
from app.shared.deps import get_calendar, get_sheet, session_factory
from app.waitlist.sync import sync_pending as sync_waitlist

log = logging.getLogger("opendispatch.outbox.worker")


def run_once() -> int:
    """One pass over every outbox. Returns how many writes went out.

    Each outbox gets its own session and commit, so one provider being down can't hold up
    or roll back another's writes.
    """
    sent = 0
    with session_factory()() as session:
        sent += sync_calendar(session, get_calendar())
        session.commit()

    # Only the server that takes signups has a waitlist to copy; everywhere else this
    # would be a query per pass forever, for a table that is always empty.
    if settings.waitlist_open:
        with session_factory()() as session:
            sent += sync_waitlist(session, get_sheet())
            session.commit()
    return sent


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stopping = False

    def stop(signum: int, _frame: FrameType | None) -> None:
        nonlocal stopping
        log.info("Signal %s: finishing the current pass and stopping", signum)
        stopping = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)

    log.info("Outbox worker started; polling every %ds when idle", settings.outbox_poll_seconds)
    while not stopping:
        try:
            sent = run_once()
        except Exception:
            # The database being unreachable shouldn't end the worker; the next pass retries.
            log.exception("Outbox worker pass failed; carrying on")
            sent = 0
        if sent:
            continue  # there may be more waiting; go straight round again
        for _ in range(settings.outbox_poll_seconds):
            if stopping:
                break
            time.sleep(1)  # a second at a time, so SIGTERM doesn't wait out the whole poll
    log.info("Outbox worker stopped")


if __name__ == "__main__":
    main()
