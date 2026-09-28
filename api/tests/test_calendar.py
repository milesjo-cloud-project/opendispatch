from uuid import uuid4

from app.adapters.calendar.fake import FakeCalendar
from app.domain.entities import Job


def test_fake_calendar_round_trip():
    cal = FakeCalendar()
    job = Job(company_id=uuid4(), customer_id=uuid4(), title="Clogged drain")
    event_id = cal.create_event(job, "tech@example.com")
    assert event_id in cal.events
    cal.cancel_event(event_id)
    assert event_id not in cal.events
