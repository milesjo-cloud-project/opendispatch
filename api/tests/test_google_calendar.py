"""The Google Calendar adapter, against a stubbed HTTP transport. No network, no account."""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from app.adapters.google_calendar import API, TOKEN_URL, GoogleCalendar, GoogleToken
from app.calendar.domain import CalendarEvent, EventGone

EVENT = CalendarEvent(
    job_id=uuid4(), title="Leak — Jane Doe",
    starts_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    ends_at=datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc),
    technician_email="tech@example.com",
    description="Jane Doe\n+15551230000\n12 Elm St",
    location="12 Elm St",
)


class Google:
    """Records what the adapter sent and answers with whatever the test asks for."""

    def __init__(self, events: httpx.Response | list[httpx.Response] | None = None,
                 token: httpx.Response | None = None) -> None:
        self.events = events if isinstance(events, list) else [events] if events else []
        self.token = token or httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        self.requests: list[httpx.Request] = []
        self.token_calls = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(TOKEN_URL):
            self.token_calls += 1
            return self.token
        self.requests.append(request)
        return self.events.pop(0) if self.events else httpx.Response(200, json={"id": "evt-1"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def calendar(self, calendar_id: str = "primary") -> GoogleCalendar:
        http = self.client()
        return GoogleCalendar(GoogleToken("cid", "secret", "refresh", http=http), calendar_id, http=http)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    @property
    def last_body(self) -> dict:
        return json.loads(self.last.content)


def test_creating_an_event_sends_the_job_and_returns_googles_id():
    google = Google(httpx.Response(200, json={"id": "evt-abc"}))
    assert google.calendar().create_event(EVENT) == "evt-abc"

    assert google.last.method == "POST"
    assert str(google.last.url).startswith(f"{API}/calendars/primary/events")
    body = google.last_body
    assert body["summary"] == EVENT.title
    assert body["location"] == EVENT.location
    assert body["start"]["dateTime"] == "2026-10-01T09:00:00Z"
    assert body["end"]["dateTime"] == "2026-10-01T11:00:00Z"
    # The technician is an attendee, which is how the job reaches the calendar they use
    assert body["attendees"] == [{"email": "tech@example.com"}]
    assert body["extendedProperties"]["private"]["opendispatch_job_id"] == str(EVENT.job_id)


def test_the_technician_is_told_about_every_change():
    """Without sendUpdates=all Google writes the event but never notifies the attendee."""
    google = Google()
    cal = google.calendar()
    cal.create_event(EVENT)
    cal.update_event("evt-abc", EVENT)
    cal.cancel_event("evt-abc")
    assert [r.url.params.get("sendUpdates") for r in google.requests] == ["all"] * 3


def test_updating_patches_the_existing_event():
    google = Google(httpx.Response(200, json={"id": "evt-abc"}))
    google.calendar().update_event("evt-abc", EVENT)
    assert google.last.method == "PATCH"
    assert str(google.last.url).startswith(f"{API}/calendars/primary/events/evt-abc")


def test_a_calendar_id_that_is_an_email_address_is_quoted():
    google = Google()
    google.calendar("crew@example.com").create_event(EVENT)
    assert f"{API}/calendars/crew%40example.com/events" in str(google.last.url)


@pytest.mark.parametrize("code", [404, 410])
def test_updating_an_event_somebody_deleted_says_it_is_gone(code):
    """So the sync makes a new one instead of retrying a call that can never work."""
    google = Google(httpx.Response(code, json={"error": {"message": "Not Found"}}))
    with pytest.raises(EventGone):
        google.calendar().update_event("evt-abc", EVENT)


@pytest.mark.parametrize("code", [404, 410])
def test_cancelling_an_event_that_is_already_gone_is_success(code):
    google = Google(httpx.Response(code, json={"error": {"message": "Not Found"}}))
    google.calendar().cancel_event("evt-abc")  # must not raise


def test_a_refused_write_raises_with_googles_reason():
    google = Google(httpx.Response(403, text='{"error": "insufficientPermissions"}'))
    with pytest.raises(RuntimeError, match="insufficientPermissions"):
        google.calendar().create_event(EVENT)


def test_a_provider_outage_raises_so_the_outbox_retries():
    google = Google(httpx.Response(503, text="backend error"))
    with pytest.raises(RuntimeError, match="503"):
        google.calendar().create_event(EVENT)


# --- the access token

def test_the_access_token_is_fetched_once_and_reused():
    google = Google()
    cal = google.calendar()
    cal.create_event(EVENT)
    cal.create_event(EVENT)
    assert google.token_calls == 1
    assert google.last.headers["Authorization"] == "Bearer at-1"


def test_a_token_about_to_expire_is_replaced():
    google = Google(token=httpx.Response(200, json={"access_token": "at-1", "expires_in": 30}))
    token = GoogleToken("cid", "secret", "refresh", http=google.client())
    token.access_token()
    token.access_token()
    assert google.token_calls == 2  # 30s left is inside the EARLY window


def test_a_revoked_refresh_token_raises_rather_than_failing_quietly():
    google = Google(token=httpx.Response(400, text='{"error": "invalid_grant"}'))
    with pytest.raises(RuntimeError, match="invalid_grant"):
        google.calendar().create_event(EVENT)


def test_a_naive_time_is_refused_rather_than_guessed_as_utc():
    google = Google()
    naive = CalendarEvent(job_id=uuid4(), title="Leak",
                          starts_at=datetime(2026, 10, 1, 9, 0), ends_at=datetime(2026, 10, 1, 11, 0),
                          technician_email="tech@example.com")
    with pytest.raises(ValueError):
        google.calendar().create_event(naive)


def test_times_are_converted_to_utc_not_sent_as_local():
    google = Google()
    offset = timezone(timedelta(hours=-5))
    event = CalendarEvent(job_id=uuid4(), title="Leak",
                          starts_at=datetime(2026, 10, 1, 9, 0, tzinfo=offset),
                          ends_at=datetime(2026, 10, 1, 11, 0, tzinfo=offset),
                          technician_email="tech@example.com")
    google.calendar().create_event(event)
    assert google.last_body["start"]["dateTime"] == "2026-10-01T14:00:00Z"
