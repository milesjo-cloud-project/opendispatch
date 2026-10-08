"""Google Sheets (shared.ports.SpreadsheetPort). Plain REST over httpx, like the calendar
adapter: no Google SDK, and the same OAuth refresh token machinery (adapters/google_auth.py).

Writes to fixed cell ranges with values:batchUpdate rather than appending rows. Appending
is what the API is built for, but it can't be retried: a call that timed out after Google
had written the row would add the same person twice, and there is no request id to stop
it. A row number owned by the signup makes every write an overwrite, so retrying is free
(see waitlist/sheet.py).

Both ranges of a write go in one call, so the header and the row can't disagree, and one
signup costs one request.
"""
import logging
from collections.abc import Mapping, Sequence

import httpx

from app.adapters.google_auth import GoogleToken

log = logging.getLogger("opendispatch.sheets")

API = "https://sheets.googleapis.com/v4/spreadsheets"
# Read/write on the spreadsheets this account can reach. There is no narrower scope: the
# file-scoped alternative (drive.file) only covers files the app itself created, and this
# writes to a sheet the owner made and shared.
SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def column_name(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA. Sheets ranges are in letters, and the waitlist already
    has eleven columns, so counting past Z has to work."""
    if index < 0:
        raise ValueError("A column index starts at 0")
    name = ""
    while True:
        index, rest = divmod(index, 26)
        name = chr(ord("A") + rest) + name
        if index == 0:
            return name
        index -= 1


class GoogleSheets:
    """Writes numbered rows to one tab of one spreadsheet.

    `tab` is the name on the tab at the bottom of the sheet; it has to exist, because
    creating one needs the spreadsheets.batchUpdate structure API and the owner naming a
    tab once is simpler than the app guessing.
    """

    def __init__(self, token: GoogleToken, spreadsheet_id: str, tab: str = "Waitlist",
                 http: httpx.Client | None = None) -> None:
        self.token = token
        self.spreadsheet_id = spreadsheet_id
        self.tab = tab
        self.http = http or httpx.Client(timeout=15)

    def _range(self, row_number: int, width: int) -> str:
        """An A1 range for one row, e.g. "'Waitlist'!A7:K7".

        Quoted and with any quote in the name doubled, which is how A1 escapes it: a tab
        called "Jo's list" would otherwise end the string early and Google would read the
        rest as a different range.
        """
        if row_number < 1:
            raise ValueError("A spreadsheet row starts at 1")
        tab = self.tab.replace("'", "''")
        last = column_name(max(width - 1, 0))
        return f"'{tab}'!A{row_number}:{last}{row_number}"

    def write_rows(self, rows: Mapping[int, Sequence[str]]) -> None:
        if not rows:
            return
        body = {
            # RAW, not USER_ENTERED: a cell starting with "=" or "+" is then text rather
            # than a formula, so nothing anyone types into the public form is evaluated.
            "valueInputOption": "RAW",
            "data": [
                {"range": self._range(number, len(values)), "values": [list(values)]}
                for number, values in sorted(rows.items())
            ],
        }
        r = self.http.post(
            f"{API}/{self.spreadsheet_id}/values:batchUpdate",
            json=body,
            headers={"Authorization": f"Bearer {self.token.access_token()}"},
        )
        if r.status_code >= 400:
            # Google's error body names the problem (no such spreadsheet, no such tab, no
            # permission). It carries no credentials, so it's safe to put in an outbox row.
            raise RuntimeError(
                f"Google Sheets refused the write: {r.status_code} {r.text[:300]}")
        log.debug("Wrote %d row(s) to spreadsheet %s", len(rows), self.spreadsheet_id)
