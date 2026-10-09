"""Which spreadsheet adapter, and which way of authenticating, get_sheet() picks.

The choice matters more than it looks: picking the log adapter when a spreadsheet *was*
configured means signups quietly never arrive, and picking the refresh token over a
service account means the whole thing stops working a week later.
"""
import json

import pytest

from app.adapters.google_sheets import GoogleSheets
from app.adapters.sheets import LogSheet
from app.config import settings
from app.shared.deps import get_sheet

KEY = pytest.importorskip("cryptography", reason="see requirements-sheets.txt")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from app.adapters.google_auth import GoogleToken  # noqa: E402
from app.adapters.google_service_account import ServiceAccountToken  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_cache():
    """get_sheet is lru_cached, so each test needs its own look at the settings."""
    get_sheet.cache_clear()
    yield
    get_sheet.cache_clear()


@pytest.fixture(scope="module")
def key_json():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return json.dumps({"type": "service_account",
                       "client_email": "waitlist@opendispatch.iam.gserviceaccount.com",
                       "private_key": pem})


def configure(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


def test_nothing_configured_writes_to_the_log(monkeypatch):
    configure(monkeypatch, google_sheets_id=None, google_service_account_json=None,
              google_service_account_file=None)
    assert isinstance(get_sheet(), LogSheet)


def test_a_service_account_is_used_when_one_is_set(monkeypatch, key_json):
    from pydantic import SecretStr

    configure(monkeypatch, google_sheets_id="sheet-1", google_sheets_tab="Waitlist",
              google_service_account_file=None,
              google_service_account_json=SecretStr(key_json))
    sheet = get_sheet()
    assert isinstance(sheet, GoogleSheets)
    assert isinstance(sheet.token, ServiceAccountToken)
    assert sheet.spreadsheet_id == "sheet-1"


def test_the_service_account_is_preferred_over_a_refresh_token(monkeypatch, key_json):
    """A refresh token under a Testing consent screen dies every 7 days; this doesn't."""
    from pydantic import SecretStr

    configure(monkeypatch, google_sheets_id="sheet-1", google_sheets_tab="Waitlist",
              google_client_id="cid", google_client_secret=SecretStr("secret"),
              google_refresh_token=SecretStr("refresh"),
              google_service_account_file=None,
              google_service_account_json=SecretStr(key_json))
    assert isinstance(get_sheet().token, ServiceAccountToken)


def test_the_refresh_token_is_used_when_there_is_no_service_account(monkeypatch):
    from pydantic import SecretStr

    configure(monkeypatch, google_sheets_id="sheet-1", google_sheets_tab="Waitlist",
              google_client_id="cid", google_client_secret=SecretStr("secret"),
              google_refresh_token=SecretStr("refresh"),
              google_sheets_refresh_token=None,
              google_service_account_file=None, google_service_account_json=None)
    assert isinstance(get_sheet().token, GoogleToken)


def test_the_scope_asked_for_is_the_spreadsheets_one(monkeypatch, key_json):
    from pydantic import SecretStr

    from app.adapters.google_sheets import SCOPE

    configure(monkeypatch, google_sheets_id="sheet-1", google_sheets_tab="Waitlist",
              google_service_account_file=None,
              google_service_account_json=SecretStr(key_json))
    assert get_sheet().token.scope == SCOPE
