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


@pytest.fixture
def tx_session():
    """A session whose commits are only savepoints inside one outer transaction that's
    rolled back at the end. For testing code (like API routes) that calls commit()."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.adapters.db.session import sqlalchemy_url
    from app.adapters.db.tables import start_mappers

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    start_mappers()
    engine = create_engine(sqlalchemy_url(url), connect_args={"connect_timeout": 5})
    try:
        conn = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"Postgres not available: {exc}")
    outer = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        outer.rollback()
        conn.close()
        engine.dispose()
