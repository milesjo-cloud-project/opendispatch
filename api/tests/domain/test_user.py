from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.shared.errors import DomainRuleViolation
from app.shared.models import User, UserRole


def test_email_is_normalized():
    user = User(company_id=uuid4(), email="  Bob@Example.COM ", role="owner")
    assert user.email == "bob@example.com"


def test_role_string_becomes_enum():
    assert User(company_id=uuid4(), email="a@b.com", role="dispatcher").role is UserRole.DISPATCHER


def test_unknown_role_is_rejected():
    with pytest.raises(DomainRuleViolation):
        User(company_id=uuid4(), email="a@b.com", role="superadmin")


def test_disable_and_enable():
    user = User(company_id=uuid4(), email="a@b.com", role="technician")
    assert not user.is_disabled
    when = datetime(2026, 10, 2, tzinfo=timezone.utc)
    user.disable(when)
    user.disable()  # disabling again keeps the original time
    assert user.is_disabled and user.disabled_at == when
    user.enable()
    assert not user.is_disabled
