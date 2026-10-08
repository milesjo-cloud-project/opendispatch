"""The launch waitlist: the public form, and the list for whoever runs the server.

Every route here is off unless WAITLIST=open. The default is "closed" because most
installs are a contractor running OpenDispatch for their own business, and they should
not be collecting signups for someone else's launch. Only opendispatch.dev turns it on.

The public routes need no login, so they say as little as possible: a closed waitlist
answers 404 rather than explaining itself. Sending is limited per IP address
(settings.waitlist_limit_per_hour) and has a honeypot field for bots.

Reading the list is guarded by WAITLIST_ADMIN_TOKEN, not by a user role. A signup has no
company (see domain.py), so there is no owner it could belong to, and a company owner on
a hosted server must never be able to read everyone else's contact details.
"""
import secrets
from collections.abc import Callable
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.shared import rate_limit
from app.shared.deps import client_ip, get_session, get_waitlist_syncer
from app.waitlist import service as waitlist
from app.waitlist import sync
from app.waitlist.domain import FOUNDING_SPOTS
from app.waitlist.schemas import (
    WaitlistJoinedOut,
    WaitlistJoinIn,
    WaitlistReportOut,
    WaitlistResyncedOut,
    WaitlistStatusOut,
)

router = APIRouter(tags=["launch waitlist"])
WAITLIST_WINDOW = timedelta(hours=1)
DAY = timedelta(hours=24)


def waitlist_open() -> None:
    """Refuse every route in this file unless this server is the one taking signups."""
    if not settings.waitlist_open:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def admin(x_waitlist_token: str | None = Header(default=None)) -> None:
    """Whoever holds WAITLIST_ADMIN_TOKEN. No token configured means nobody, not everybody."""
    expected = settings.waitlist_admin_token
    supplied = x_waitlist_token or ""
    # compare_digest on both, and only after the None check, so a wrong token and a
    # missing one take the same path and neither leaks the length of the real one.
    if expected is None or not secrets.compare_digest(supplied, expected.get_secret_value()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


# --- public: no login

@router.get("/public/waitlist", response_model=WaitlistStatusOut,
            dependencies=[Depends(waitlist_open)])
def waitlist_status(session: Session = Depends(get_session)):
    """What the page shows before anyone types: how many founding spots are left."""
    return WaitlistStatusOut(founding_spots=FOUNDING_SPOTS,
                             spots_left=waitlist.spots_left(session),
                             launch=settings.launch_label)


@router.post("/public/waitlist", response_model=WaitlistJoinedOut, status_code=201,
             dependencies=[Depends(waitlist_open)])
def join_waitlist(body: WaitlistJoinIn, request: Request, background: BackgroundTasks,
                  session: Session = Depends(get_session),
                  sync_sheet: Callable[[], None] = Depends(get_waitlist_syncer)):
    if not rate_limit.allow(session, "waitlist", client_ip(request),
                            limit=settings.waitlist_limit_per_hour, window=WAITLIST_WINDOW):
        session.commit()  # keep the cleanup of old hits
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Too many signups from your network. Please try again later.",
                            headers={"Retry-After": str(int(WAITLIST_WINDOW.total_seconds()))})
    session.commit()  # the hit stays counted even if what follows is refused

    if body.website:
        # A bot. It gets a plausible answer so it can't tell it was caught, and nothing is saved.
        return WaitlistJoinedOut(spot=FOUNDING_SPOTS + 1, is_founding=False,
                                 already_on_list=False, spots_left=0)

    signup, is_new = waitlist.join(session, **body.model_dump(exclude={"website"}))
    if is_new:
        # In the same transaction as the signup, so a rolled-back signup queues no
        # spreadsheet row. A repeat signup changes nothing, so it queues nothing.
        sync.mark_dirty(session, signup)
    session.commit()
    if is_new:
        # After the response: nobody should wait on Google to be told their spot, and a
        # spreadsheet that's down must not turn a signup into an error.
        background.add_task(sync_sheet)
    return WaitlistJoinedOut(spot=signup.spot, is_founding=signup.is_founding,
                             already_on_list=not is_new, spots_left=waitlist.spots_left(session))


# --- whoever runs the server

@router.get("/waitlist", response_model=WaitlistReportOut,
            dependencies=[Depends(waitlist_open), Depends(admin)])
def waitlist_report(session: Session = Depends(get_session)):
    """The list and the numbers worth watching. Needs the X-Waitlist-Token header."""
    rows = waitlist.signups(session)
    return WaitlistReportOut(total=len(rows),
                             spots_left=waitlist.spots_left(session),
                             last_24_hours=waitlist.recent(session, within=DAY),
                             by_plan=waitlist.counts_by_plan(session),
                             signups=rows)


@router.post("/waitlist/resync", response_model=WaitlistResyncedOut,
             dependencies=[Depends(waitlist_open), Depends(admin)])
def resync_waitlist(background: BackgroundTasks, session: Session = Depends(get_session),
                    sync_sheet: Callable[[], None] = Depends(get_waitlist_syncer)):
    """Queue every signup for the spreadsheet again. Needs the X-Waitlist-Token header.

    For a spreadsheet set up after people had already signed up, or one that was replaced
    or ruined. Each row goes back where it was, because a signup's row number comes from
    its spot, so this is safe to run as often as you like.
    """
    queued = sync.queue_all(session)
    session.commit()
    background.add_task(sync_sheet)
    return WaitlistResyncedOut(queued=queued)
