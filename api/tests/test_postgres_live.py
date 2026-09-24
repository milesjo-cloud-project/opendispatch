"""Runs only when a real Postgres is reachable (CI provides one; skipped otherwise)."""

import os

import pytest

from app.adapters.db.postgres import PostgresHealth

DB_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")
def test_postgres_ping():
    assert PostgresHealth(DB_URL).ping() is True
