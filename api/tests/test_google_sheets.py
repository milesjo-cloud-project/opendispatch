"""The Google Sheets adapter, against a stubbed HTTP transport. No network, no account."""
import json

import httpx
import pytest

from app.adapters.google_auth import TOKEN_URL, GoogleToken
from app.adapters.google_sheets import API, GoogleSheets, column_name

ROWS = {
    1: ["Spot", "Email", "Name"],
    7: ["6", "pat@example.com", "Pat Jones"],
}


class Google:
    """Records what the adapter sent and answers with whatever the test asks for."""

    def __init__(self, write: httpx.Response | None = None,
                 token: httpx.Response | None = None) -> None:
        self.write = write or httpx.Response(200, json={"totalUpdatedCells": 3})
        self.token = token or httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        self.requests: list[httpx.Request] = []
        self.token_calls = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(TOKEN_URL):
            self.token_calls += 1
            return self.token
        self.requests.append(request)
        return self.write

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def sheets(self, spreadsheet_id: str = "sheet-1", tab: str = "Waitlist") -> GoogleSheets:
        http = self.client()
        return GoogleSheets(GoogleToken("cid", "secret", "refresh", http=http),
                            spreadsheet_id, tab, http=http)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    @property
    def last_body(self) -> dict:
        return json.loads(self.last.content)


def test_a_write_sends_every_row_in_one_call():
    """One signup is one request, so the header can't land without the row it labels."""
    google = Google()
    google.sheets().write_rows(ROWS)

    assert len(google.requests) == 1
    assert google.last.method == "POST"
    assert str(google.last.url) == f"{API}/sheet-1/values:batchUpdate"
    body = google.last_body
    assert [d["range"] for d in body["data"]] == ["'Waitlist'!A1:C1", "'Waitlist'!A7:C7"]
    assert [d["values"] for d in body["data"]] == [[ROWS[1]], [ROWS[7]]]


def test_cells_are_sent_raw_so_nothing_typed_into_the_form_becomes_a_formula():
    google = Google()
    google.sheets().write_rows({2: ["=IMPORTXML(...)", "pat@example.com"]})
    assert google.last_body["valueInputOption"] == "RAW"


def test_a_row_is_written_to_the_range_it_owns():
    """The row number is the signup's, so writing twice overwrites instead of appending."""
    google = Google()
    google.sheets().write_rows({42: ["a", "b"]})
    assert google.last_body["data"][0]["range"] == "'Waitlist'!A42:B42"


def test_a_tab_name_with_an_apostrophe_is_escaped():
    google = Google()
    google.sheets(tab="Jo's list").write_rows({2: ["a"]})
    assert google.last_body["data"][0]["range"] == "'Jo''s list'!A2:A2"


def test_writing_nothing_makes_no_request():
    google = Google()
    google.sheets().write_rows({})
    assert google.requests == []


def test_row_zero_is_refused_rather_than_written_somewhere_odd():
    google = Google()
    with pytest.raises(ValueError):
        google.sheets().write_rows({0: ["a"]})


def test_a_refused_write_raises_with_googles_reason_so_the_outbox_retries():
    google = Google(httpx.Response(400, text='{"error": "Unable to parse range: Waitlist"}'))
    with pytest.raises(RuntimeError, match="Unable to parse range"):
        google.sheets().write_rows(ROWS)


def test_a_provider_outage_raises_so_the_outbox_retries():
    google = Google(httpx.Response(503, text="backend error"))
    with pytest.raises(RuntimeError, match="503"):
        google.sheets().write_rows(ROWS)


def test_a_revoked_refresh_token_raises_rather_than_failing_quietly():
    google = Google(token=httpx.Response(400, text='{"error": "invalid_grant"}'))
    with pytest.raises(RuntimeError, match="invalid_grant"):
        google.sheets().write_rows(ROWS)


def test_the_access_token_is_fetched_once_and_reused():
    google = Google()
    sheet = google.sheets()
    sheet.write_rows(ROWS)
    sheet.write_rows(ROWS)
    assert google.token_calls == 1
    assert google.last.headers["Authorization"] == "Bearer at-1"


# --- A1 columns

@pytest.mark.parametrize("index,name", [
    (0, "A"), (1, "B"), (25, "Z"), (26, "AA"), (27, "AB"), (51, "AZ"), (52, "BA"), (701, "ZZ"),
])
def test_column_names_carry_past_z(index, name):
    """The waitlist already has eleven columns, so counting past Z has to work."""
    assert column_name(index) == name


def test_a_negative_column_is_refused():
    with pytest.raises(ValueError):
        column_name(-1)
