"""Login rules: password policy, lockout, sessions, phone numbers. No database, no argon2."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.domain.auth import (
    LOCKOUT,
    MAX_FAILED_LOGINS,
    SESSION_LIFETIME,
    AuthSession,
    check_password_policy,
    normalize_phone,
)
from app.domain.entities import User
from app.domain.errors import DomainRuleViolation

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("pw", ["correct horse", "x" * 12, "x" * 128])
def test_password_policy_accepts(pw):
    check_password_policy(pw)


@pytest.mark.parametrize("pw", ["", "short", "x" * 11, "x" * 129, " " * 20])
def test_password_policy_rejects(pw):
    with pytest.raises(DomainRuleViolation):
        check_password_policy(pw)


@pytest.mark.parametrize("raw,e164", [
    ("5551234567", "+15551234567"),
    ("(555) 123-4567", "+15551234567"),
    ("555.123.4567", "+15551234567"),
    ("1-555-123-4567", "+15551234567"),
    ("+1 555 123 4567", "+15551234567"),
    ("+44 20 7946 0958", "+442079460958"),
])
def test_phone_normalized_to_e164(raw, e164):
    assert normalize_phone(raw) == e164


@pytest.mark.parametrize("raw", ["123", "555-1234", "+0123456789", "call me", "+1234567890123456"])
def test_bad_phone_rejected(raw):
    with pytest.raises(DomainRuleViolation):
        normalize_phone(raw)


def _user(**kw) -> User:
    return User(company_id=uuid4(), email="a@example.com", role="owner", **kw)


def test_user_phone_is_normalized_and_clearable():
    user = _user(phone="(555) 123-4567")
    assert user.phone == "+15551234567"
    user.set_phone(None)
    assert user.phone is None
    user.set_phone("")
    assert user.phone is None


def test_lockout_after_max_failures():
    user = _user()
    for _ in range(MAX_FAILED_LOGINS - 1):
        user.record_failed_login(NOW)
    assert not user.is_locked(NOW)

    user.record_failed_login(NOW)
    assert user.is_locked(NOW)
    assert user.is_locked(NOW + LOCKOUT - timedelta(seconds=1))
    assert not user.is_locked(NOW + LOCKOUT)


def test_success_resets_failures():
    user = _user()
    for _ in range(MAX_FAILED_LOGINS - 1):
        user.record_failed_login(NOW)
    user.record_successful_login()
    user.record_failed_login(NOW)
    assert not user.is_locked(NOW)
    assert user.failed_logins == 1


def test_session_expires_and_revokes():
    s = AuthSession(user_id=uuid4(), company_id=uuid4(), token_hash="h")
    assert s.is_active()
    assert s.expires_at - s.created_at == SESSION_LIFETIME
    assert not s.is_active(s.expires_at)
    s.revoke()
    assert not s.is_active()
