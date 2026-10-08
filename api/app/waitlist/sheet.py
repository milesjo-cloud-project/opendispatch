"""The launch waitlist as a spreadsheet: which columns, and which row each signup owns.

No database and no HTTP here. sync.py loads the signups, this turns one into cells, and
the adapters behind SpreadsheetPort write them.

A signup's row number is its spot plus one, because the header is row 1. That is the whole
trick that makes the sync safe to retry: spots are handed out in order, starting at 1, and
never reused (waitlist/domain.py), so every signup has one row that is only ever its own.
Writing it twice overwrites the same cells instead of appending a duplicate, which an
"append a row" call could never promise once a write has timed out after Google acted.
"""
from collections.abc import Mapping, Sequence

from app.waitlist.domain import WaitlistSignup

# What the header says, and the order of the cells in row_for(). Append new columns at the
# end: a column inserted in the middle would mislabel every row already in the sheet, and
# nothing rewrites the rows that are already sent.
COLUMNS = (
    "Spot",
    "Joined (UTC)",
    "Email",
    "Name",
    "Company",
    "Trade",
    "Crew size",
    "Plan",
    "Current tool",
    "Region",
    "Founding",
)

HEADER_ROW = 1


def row_number(signup: WaitlistSignup) -> int:
    """The spreadsheet row this signup owns, for as long as the sheet exists."""
    return signup.spot + HEADER_ROW


def row_for(signup: WaitlistSignup) -> list[str]:
    """One signup as cells, in COLUMNS order. Everything is text: a spreadsheet would
    otherwise read a crew size of "2-3" as a date, and a region as a formula."""
    return [
        str(signup.spot),
        signup.created_at.strftime("%Y-%m-%d %H:%M"),
        signup.email,
        signup.name or "",
        signup.company or "",
        signup.trade or "",
        signup.crew_size or "",
        signup.plan.value,
        signup.current_tool or "",
        signup.region or "",
        "yes" if signup.is_founding else "",
    ]


def rows_for(signup: WaitlistSignup) -> Mapping[int, Sequence[str]]:
    """What to write for this signup: its own row, and the header.

    The header goes with every write on purpose. It costs nothing (the adapter sends both
    ranges in one call) and it means a brand-new, empty spreadsheet comes out labelled
    without a separate setup step anyone could forget.
    """
    return {HEADER_ROW: list(COLUMNS), row_number(signup): row_for(signup)}
