"""Spreadsheet adapters (shared.ports.SpreadsheetPort) for when there's no real
spreadsheet: the API log when Google Sheets isn't configured, and an in-memory fake for
tests. The Google adapter lives in adapters/google_sheets.py."""
import logging
from collections.abc import Mapping, Sequence

log = logging.getLogger("opendispatch.sheets")


class LogSheet:
    """Writes the rows to the API log instead of a spreadsheet.

    Used when GOOGLE_SHEETS_ID isn't set, which is every install except the project's own
    server: the outbox still drains, so nothing piles up waiting for a sheet that will
    never exist.

    Locally it logs the cells, so you can see the sync working. Anywhere else it logs only
    that rows were dropped: a waitlist row is somebody's name, email address and business,
    and logs get shipped and kept.
    """

    def __init__(self, show_details: bool) -> None:
        self.show_details = show_details

    def write_rows(self, rows: Mapping[int, Sequence[str]]) -> None:
        if self.show_details:
            for number, values in sorted(rows.items()):
                log.warning("SHEET ROW %d (not sent, Google Sheets not configured): %s",
                            number, " | ".join(values))
        else:
            log.info("%d spreadsheet row(s) were not sent: Google Sheets isn't configured",
                     len(rows))


class FakeSheet:
    """In-memory spreadsheet for tests. `fail` makes every call raise, for the retry tests."""

    def __init__(self, fail: bool = False) -> None:
        self.rows: dict[int, list[str]] = {}
        self.writes: list[dict[int, list[str]]] = []
        self.fail = fail

    def write_rows(self, rows: Mapping[int, Sequence[str]]) -> None:
        if self.fail:
            raise ConnectionError("spreadsheet provider is down")
        self.writes.append({number: list(values) for number, values in rows.items()})
        for number, values in rows.items():
            self.rows[number] = list(values)
