"""Integration tests need a migrated database at TEST_DATABASE_URL (CI provides one):
    alembic upgrade head
They're skipped when TEST_DATABASE_URL isn't set or the database can't be reached.
"""
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError


@pytest.fixture
def session():
    from app.adapters.db.session import make_session_factory

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    try:
        factory = make_session_factory(url)
        s = factory()
        s.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"Postgres not available: {exc}")
    try:
        yield s
    finally:
        s.rollback()  # nothing from this test is kept
        s.close()
