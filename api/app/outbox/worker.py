"""Drains every outbox on a timer: `python -m app.outbox.worker`.

The API already drains them in a background task after the request that queued the write,
which covers the normal case. This retries a deferred write if a request ended before its
background task could complete.

One process handles the outbox because it shares a retry policy
(app/shared/outbox.py). One replica is enough; SKIP LOCKED makes more than one safe,
not faster.
"""
import logging
import signal
import time
from types import FrameType

from app.calendar.service import sync_pending as sync_calendar
from app.config import settings
from app.shared.deps import get_calendar, session_factory

log = logging.getLogger("opendispatch.outbox.worker")


def run_once() -> int:
    """One pass over the calendar outbox. Returns how many writes were handled.

    The outbox gets its own session and commit.
    """
    sent = 0
    with session_factory()() as session:
        sent += sync_calendar(session, get_calendar())
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
