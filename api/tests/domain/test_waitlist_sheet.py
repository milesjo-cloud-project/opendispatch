"""Which row a signup owns in the launch spreadsheet, and what goes in it."""
from datetime import datetime, timezone

from app.waitlist.domain import FOUNDING_SPOTS, PlanInterest, WaitlistSignup
from app.waitlist.sheet import COLUMNS, HEADER_ROW, row_for, row_number, rows_for

JOINED = datetime(2026, 10, 8, 14, 5, tzinfo=timezone.utc)


def signup(**overrides) -> WaitlistSignup:
    fields = dict(email="pat@example.com", spot=6, name="Pat Jones", company="Jones Plumbing",
                  trade="plumbing", crew_size="2-3", plan=PlanInterest.PERPETUAL,
                  current_tool="paper and a whiteboard", region="Boise, ID")
    return WaitlistSignup(**(fields | overrides), created_at=JOINED)


def test_a_signup_owns_the_row_below_its_spot():
    """Spot 1 is row 2, because the header is row 1."""
    assert HEADER_ROW == 1
    assert row_number(signup(spot=1)) == 2
    assert row_number(signup(spot=6)) == 7


def test_the_row_number_never_moves():
    """It comes from the spot, so writing the same signup twice overwrites one row.
    That is what makes the outbox safe to retry against a spreadsheet."""
    pat = signup(spot=6)
    assert row_number(pat) == row_number(signup(spot=6, email="someone@else.com"))
    assert rows_for(pat).keys() == rows_for(pat).keys()


def test_the_row_matches_the_header_column_for_column():
    row = row_for(signup())
    assert len(row) == len(COLUMNS)
    assert dict(zip(COLUMNS, row, strict=True)) == {
        "Spot": "6",
        "Joined (UTC)": "2026-10-08 14:05",
        "Email": "pat@example.com",
        "Name": "Pat Jones",
        "Company": "Jones Plumbing",
        "Trade": "plumbing",
        "Crew size": "2-3",
        "Plan": "perpetual",
        "Current tool": "paper and a whiteboard",
        "Region": "Boise, ID",
        "Founding": "yes",
    }


def test_blanks_are_empty_cells_not_the_word_none():
    row = row_for(signup(name=None, company=None, trade=None, crew_size=None,
                         current_tool=None, region=None))
    assert "" in row and "None" not in row


def test_a_spot_past_the_founding_hundred_is_not_marked_founding():
    assert row_for(signup(spot=FOUNDING_SPOTS))[-1] == "yes"
    assert row_for(signup(spot=FOUNDING_SPOTS + 1))[-1] == ""


def test_every_write_carries_the_header_so_a_new_sheet_comes_out_labelled():
    rows = rows_for(signup(spot=6))
    assert rows[HEADER_ROW] == list(COLUMNS)
    assert rows[7] == row_for(signup(spot=6))
    assert len(rows) == 2
