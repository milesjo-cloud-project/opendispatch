"""Google Calendar (shared.ports.CalendarPort). Plain REST over httpx, like the Twilio
adapter: no Google SDK, so a self-hoster installs nothing beyond requirements.txt.

Authenticated as the Google account whose calendar the jobs go on, with an OAuth refresh
token (README says how to get one; adapters/google_auth.py does the refreshing). That's
deliberately not a service account: a service account can't invite attendees without
Google Workspace domain-wide delegation, so the technician would never see the job in
their own calendar, which is the whole point.
"""
import logging
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from app.adapters.google_auth import TOKEN_URL, AccessTokenSource, GoogleToken
from app.calendar.domain import CalendarEvent, EventGone

log = logging.getLogger("opendispatch.calendar")

# Re-exported so `from app.adapters.google_calendar import GoogleToken` still reads
# naturally where the calendar is the only Google thing in view.
__all__ = ["API", "SCOPE", "TOKEN_URL", "GoogleCalendar", "GoogleToken"]

API = "https://www.googleapis.com/calendar/v3"
# Enough to manage our own events; not enough to read or delete the account's calendars.
SCOPE = "https://www.googleapis.com/auth/calendar.events"

# The provider has forgotten the event. Both mean the same thing to us: it isn't there.
MISSING = (404, 410)


def _rfc3339(when: datetime) -> str:
    """Google wants an offset, so a naive time would silently be read as UTC anyway."""
    if when.tzinfo is None:
        raise ValueError("Calendar times must include a time zone")
    return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class GoogleCalendar:
    """Creates, updates and cancels one event per job on a single Google calendar.

    The technician is an attendee rather than the calendar's owner, so the event lands in
    whatever calendar they already use, Google account or not. `sendUpdates=all` is what
    makes Google send them the invite and the changes.
    """

    def __init__(self, token: AccessTokenSource, calendar_id: str = "primary",
                 http: httpx.Client | None = None) -> None:
        self.token = token
        self.calendar_id = calendar_id
        self.http = http or httpx.Client(timeout=15)

    def _events_url(self, external_id: str | None = None) -> str:
        # A calendar id is an email address for anything but "primary", so it needs quoting.
        base = f"{API}/calendars/{quote(self.calendar_id, safe='')}/events"
        return f"{base}/{quote(external_id, safe='')}" if external_id else base

    def _body(self, event: CalendarEvent) -> dict:
        return {
            "summary": event.title,
            "description": event.description or "",
            "location": event.location or "",
            "start": {"dateTime": _rfc3339(event.starts_at)},
            "end": {"dateTime": _rfc3339(event.ends_at)},
            "attendees": [{"email": event.technician_email}],
            # Lets a human (or a later feature) trace an event back to the job it's for.
            "extendedProperties": {"private": {"opendispatch_job_id": str(event.job_id)}},
            "guestsCanModify": False,
            "reminders": {"useDefault": True},
        }

    def _call(self, method: str, url: str, *, json: dict | None = None) -> httpx.Response:
        return self.http.request(
            method, url,
            params={"sendUpdates": "all"},
            json=json,
            headers={"Authorization": f"Bearer {self.token.access_token()}"},
        )

    def _refuse(self, r: httpx.Response, what: str) -> RuntimeError:
        # Google's error body names the problem (bad calendar id, no permission, bad
        # attendee). It carries no credentials, so it's safe to put in an outbox row.
        return RuntimeError(f"Google Calendar refused to {what}: {r.status_code} {r.text[:300]}")

    def create_event(self, event: CalendarEvent) -> str:
        r = self._call("POST", self._events_url(), json=self._body(event))
        if r.status_code >= 400:
            raise self._refuse(r, "create the event")
        return r.json()["id"]

    def update_event(self, external_id: str, event: CalendarEvent) -> None:
        # PATCH, not PUT: it leaves fields we don't set (the attendee's own response,
        # their reminders) alone.
        r = self._call("PATCH", self._events_url(external_id), json=self._body(event))
        if r.status_code in MISSING:
            raise EventGone(external_id)
        if r.status_code >= 400:
            raise self._refuse(r, "update the event")

    def cancel_event(self, external_id: str) -> None:
        r = self._call("DELETE", self._events_url(external_id))
        if r.status_code in MISSING:
            log.info("Calendar event %s was already gone", external_id)
            return
        if r.status_code >= 400:
            raise self._refuse(r, "cancel the event")
