"""waitlist/service.py against a real database: spots, repeat signups, and the counts.

The waitlist is not tenant-scoped, so these tests need no company fixture. They also can't
assume an empty table (the `session` fixture rolls back but other rows may exist in a dev
database), so every assertion is relative to what was already there.
"""
import pytest
from sqlalchemy import func, select

from app.db.tables import waitlist_signups
from app.shared.errors import DomainRuleViolation
from app.waitlist import service as waitlist
from app.waitlist.domain import FOUNDING_SPOTS, PlanInterest

pytestmark = pytest.mark.integration


def total(session) -> int:
    return session.scalar(select(func.count()).select_from(waitlist_signups)) or 0


def highest(session) -> int:
    return session.scalar(select(func.max(waitlist_signups.c.spot))) or 0


def test_first_signup_takes_the_next_spot(session):
    before = highest(session)
    signup, is_new = waitlist.join(session, email="pat@example.com", name="Pat Jones")
    assert is_new
    assert signup.spot == before + 1
    assert signup.email == "pat@example.com"


def test_spots_are_handed_out_in_order(session):
    first, _ = waitlist.join(session, email="one@example.com")
    second, _ = waitlist.join(session, email="two@example.com")
    third, _ = waitlist.join(session, email="three@example.com")
    assert [second.spot, third.spot] == [first.spot + 1, first.spot + 2]


def test_signing_up_twice_keeps_the_original_spot_and_saves_nothing_new(session):
    first, is_new = waitlist.join(session, email="pat@example.com", company="Whitfield")
    assert is_new
    rows_after_first = total(session)

    again, is_new_again = waitlist.join(session, email="pat@example.com", company="Somewhere Else")
    assert not is_new_again
    assert again.spot == first.spot
    assert again.company == "Whitfield"  # the second answer is dropped, not applied
    assert total(session) == rows_after_first


def test_a_different_capitalisation_is_the_same_person(session):
    first, _ = waitlist.join(session, email="Pat@Example.com")
    again, is_new = waitlist.join(session, email="PAT@EXAMPLE.COM")
    assert not is_new
    assert again.spot == first.spot


def test_a_bad_email_is_refused_and_takes_no_spot(session):
    before = highest(session)
    with pytest.raises(DomainRuleViolation):
        waitlist.join(session, email="not-an-email")
    session.rollback()
    assert highest(session) == before


def test_spots_left_counts_down_from_the_founding_limit(session):
    before = waitlist.spots_left(session)
    assert before == max(0, FOUNDING_SPOTS - total(session))
    waitlist.join(session, email="pat@example.com")
    assert waitlist.spots_left(session) == max(0, before - 1)


def test_spots_left_never_goes_below_zero(session, monkeypatch):
    monkeypatch.setattr("app.waitlist.service.FOUNDING_SPOTS", 0)
    waitlist.join(session, email="pat@example.com")
    assert waitlist.spots_left(session) == 0


def test_the_list_comes_back_in_the_order_people_joined(session):
    waitlist.join(session, email="one@example.com")
    waitlist.join(session, email="two@example.com")
    spots = [s.spot for s in waitlist.signups(session)]
    assert spots == sorted(spots)


def test_counts_by_plan_names_every_plan_even_at_zero(session):
    waitlist.join(session, email="pat@example.com", plan=PlanInterest.PERPETUAL)
    counts = waitlist.counts_by_plan(session)
    assert set(counts) == {plan.value for plan in PlanInterest}
    assert counts["perpetual"] >= 1
