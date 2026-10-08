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


# --- Google Sheets, for the launch waitlist's copy of the signups

GOOGLE = dict(google_client_id="cid", google_client_secret="secret")


def test_sheets_is_off_until_a_spreadsheet_is_named():
    """Every install that isn't taking signups should write the rows to the log."""
    settings = Settings(_env_file=None, google_refresh_token="refresh", **GOOGLE)
    assert settings.google_sheets_configured is False


def test_sheets_reuses_the_calendar_token_when_it_has_no_token_of_its_own():
    """One token consented with both scopes is the simplest setup, so it's the default."""
    settings = Settings(_env_file=None, google_refresh_token="refresh",
                        google_sheets_id="sheet-1", **GOOGLE)
    assert settings.sheets_refresh_token == "refresh"
    assert settings.google_sheets_configured is True


def test_sheets_prefers_its_own_token_when_one_is_set():
    settings = Settings(_env_file=None, google_refresh_token="calendar-refresh",
                        google_sheets_refresh_token="sheets-refresh",
                        google_sheets_id="sheet-1", **GOOGLE)
    assert settings.sheets_refresh_token == "sheets-refresh"


def test_a_spreadsheet_with_no_token_at_all_is_not_configured():
    settings = Settings(_env_file=None, google_sheets_id="sheet-1", **GOOGLE)
    assert settings.sheets_refresh_token is None
    assert settings.google_sheets_configured is False


def test_the_tab_defaults_to_waitlist():
    assert Settings(_env_file=None).google_sheets_tab == "Waitlist"
