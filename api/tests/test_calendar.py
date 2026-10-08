from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.adapters.calendar import FakeCalendar, LogCalendar
from app.calendar.domain import CalendarEvent, EventGone


def an_event(**overrides) -> CalendarEvent:
    fields = dict(job_id=uuid4(), title="Clogged drain — Jane Doe",
                  starts_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
                  ends_at=datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc),
                  technician_email="tech@example.com", description="12 Elm St",
                  location="12 Elm St")
    fields.update(overrides)
    return CalendarEvent(**fields)


def test_fake_calendar_round_trip():
    cal = FakeCalendar()
    event = an_event()
    external_id = cal.create_event(event)
    assert cal.events[external_id] == event

    moved = an_event(job_id=event.job_id, starts_at=event.starts_at + timedelta(hours=1))
    cal.update_event(external_id, moved)
    assert cal.events[external_id] == moved

    cal.cancel_event(external_id)
    assert external_id not in cal.events


def test_cancelling_an_event_twice_is_fine():
    """The outbox retries, so cancel may well be called on something already gone."""
    cal = FakeCalendar()
    external_id = cal.create_event(an_event())
    cal.cancel_event(external_id)
    cal.cancel_event(external_id)  # must not raise
    assert cal.cancelled == [external_id, external_id]


def test_updating_an_unknown_event_says_it_is_gone():
    cal = FakeCalendar()
    with pytest.raises(EventGone):
        cal.update_event("never-existed", an_event())


def test_failing_calendar_raises_on_every_call():
    cal = FakeCalendar(fail=True)
    with pytest.raises(ConnectionError):
        cal.create_event(an_event())


def test_log_calendar_shows_the_whole_event_locally(caplog):
    """With no provider configured the sync still has to complete, and locally the log is
    how you get at the link."""
    cal = LogCalendar(show_details=True)
    with caplog.at_level("WARNING"):
        external_id = cal.create_event(an_event(description="12 Elm St\nJob details: http://x/j/tok"))
    assert external_id.startswith("log-")
    assert "http://x/j/tok" in caplog.text
    cal.update_event(external_id, an_event())
    cal.cancel_event(external_id)


def test_log_calendar_keeps_the_link_and_the_customer_out_of_the_log_elsewhere(caplog):
    """A job link is a credential, and the body carries the customer's address and phone.
    Outside local the log records only that an event was dropped, as LogEmail does."""
    cal = LogCalendar(show_details=False)
    event = an_event(description="Jane Doe\n+15551230000\n12 Elm St\n"
                                 "Job details: http://x/j/1.abc.def.123.SIGNATURE")
    with caplog.at_level("INFO"):
        external_id = cal.create_event(event)
        cal.update_event(external_id, event)

    assert external_id.startswith("log-")
    for secret in ("SIGNATURE", "/j/1.abc", "12 Elm St", "+15551230000", "Jane Doe"):
        assert secret not in caplog.text, f"{secret!r} reached the log"
    assert str(event.job_id) in caplog.text  # still traceable
