"""Waitlist rules: what a signup must contain, and which spots get the founding price."""
import pytest

from app.shared.errors import DomainRuleViolation
from app.waitlist.domain import FOUNDING_SPOTS, PlanInterest, WaitlistSignup


def signup(**overrides) -> WaitlistSignup:
    fields = dict(email="pat@example.com", spot=1)
    fields.update(overrides)
    return WaitlistSignup(**fields)


def test_email_is_lower_cased_and_text_is_trimmed():
    s = signup(email="  Pat@Example.COM ", name="  Pat Jones ", company="  ", trade=" HVAC ")
    assert (s.email, s.name, s.company, s.trade) == ("pat@example.com", "Pat Jones", None, "HVAC")


def test_plan_defaults_to_undecided():
    assert signup().plan is PlanInterest.UNDECIDED


@pytest.mark.parametrize("bad", ["", "   ", "not-an-email", "@example.com", "pat@"])
def test_signup_needs_an_email_we_can_reach(bad):
    with pytest.raises(DomainRuleViolation):
        signup(email=bad)


@pytest.mark.parametrize("bad", [0, -1])
def test_spot_starts_at_one(bad):
    with pytest.raises(DomainRuleViolation):
        signup(spot=bad)


def test_the_first_spots_are_founding_and_the_next_one_is_not():
    assert signup(spot=1).is_founding
    assert signup(spot=FOUNDING_SPOTS).is_founding
    assert not signup(spot=FOUNDING_SPOTS + 1).is_founding
