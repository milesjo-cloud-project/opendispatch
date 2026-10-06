import pytest
from pydantic import ValidationError

from app.config import Settings


def test_local_uses_default_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert Settings(_env_file=None, app_env="local").database_url.startswith("postgresql://")


def test_database_url_required_outside_local(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="DATABASE_URL must be set"):
        Settings(_env_file=None, app_env="prod")


def test_signup_defaults_to_first_run(monkeypatch):
    """A contractor's own install closes sign-up once their company exists."""
    monkeypatch.delenv("SIGNUP", raising=False)
    assert Settings(_env_file=None).signup == "first-run"


def test_signup_setting_rejects_typos(monkeypatch):
    monkeypatch.setenv("SIGNUP", "opne")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_url_from_env_is_accepted_outside_local(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/x")
    assert Settings(_env_file=None, app_env="prod").database_url == "postgresql://u:p@db:5432/x"
