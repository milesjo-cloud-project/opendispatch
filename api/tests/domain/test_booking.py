"""Booking request rules: what a public request must contain and how the office decides on it."""
from uuid import uuid4

import pytest

from app.domain.booking import BookingRequest, BookingRequestStatus
from app.domain.entities import Job, User
from app.domain.errors import DomainRuleViolation

COMPANY = uuid4()


def request(**overrides) -> BookingRequest:
    fields = dict(company_id=COMPANY, name="Pat Jones", title="Leaking tap", phone="555-0100")
    fields.update(overrides)
    return BookingRequest(**fields)


def office(company_id=COMPANY) -> User:
    return User(company_id=company_id, email="office@example.com", role="dispatcher")


def job(company_id=COMPANY) -> Job:
    return Job(company_id=company_id, customer_id=uuid4(), title="Leaking tap")


def test_new_request_is_new_and_trimmed():
    r = request(name="  Pat Jones ", title=" Leaking tap  ", email="  ")
    assert r.status == BookingRequestStatus.NEW
    assert (r.name, r.title, r.email) == ("Pat Jones", "Leaking tap", None)


@pytest.mark.parametrize("overrides", [
    {"name": "   "},
    {"title": ""},
    {"phone": None, "email": None},
    {"phone": "  ", "email": " "},
])
def test_request_needs_name_title_and_a_way_to_reach_them(overrides):
    with pytest.raises(DomainRuleViolation):
        request(**overrides)


def test_email_alone_is_enough():
    assert request(phone=None, email="pat@example.com").email == "pat@example.com"


def test_accept_links_the_job():
    r, j, by = request(), job(), office()
    r.accept(j, by)
    assert r.status == BookingRequestStatus.ACCEPTED
    assert (r.job_id, r.decided_by_user_id) == (j.id, by.id)
    assert r.decided_at is not None


def test_decline():
    r = request()
    r.decline(office())
    assert r.status == BookingRequestStatus.DECLINED
    assert r.job_id is None and r.decided_at is not None


@pytest.mark.parametrize("first", ["accept", "decline"])
def test_a_request_is_decided_once(first):
    r = request()
    r.accept(job(), office()) if first == "accept" else r.decline(office())
    with pytest.raises(DomainRuleViolation):
        r.accept(job(), office())
    with pytest.raises(DomainRuleViolation):
        r.decline(office())


def test_cant_accept_into_another_companys_job():
    r = request()
    with pytest.raises(DomainRuleViolation):
        r.accept(job(company_id=uuid4()), office())
    assert r.status == BookingRequestStatus.NEW


def test_another_company_cant_decide():
    r = request()
    with pytest.raises(DomainRuleViolation):
        r.decline(office(company_id=uuid4()))
    with pytest.raises(DomainRuleViolation):
        r.accept(job(), office(company_id=uuid4()))
    assert r.status == BookingRequestStatus.NEW
