from uuid import uuid4

import pytest

from app.domain.entities import User, UserRole
from app.domain.errors import DomainRuleViolation


def test_email_is_normalized():
    user = User(company_id=uuid4(), email="  Bob@Example.COM ", role="owner")
    assert user.email == "bob@example.com"


def test_role_string_becomes_enum():
    assert User(company_id=uuid4(), email="a@b.com", role="dispatcher").role is UserRole.DISPATCHER


def test_unknown_role_is_rejected():
    with pytest.raises(DomainRuleViolation):
        User(company_id=uuid4(), email="a@b.com", role="superadmin")
