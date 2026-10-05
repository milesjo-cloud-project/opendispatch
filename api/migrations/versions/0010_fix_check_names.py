"""rename CHECK constraints that came out with their prefix twice

Migrations 0003 and 0004 wrote full names (ck_expenses_amount_positive), and the naming
convention added ck_<table>_ again, giving ck_expenses_ck_expenses_amount_positive. Only the
names change; what each constraint checks stays the same.

Revision ID: 0010_fix_check_names
Revises: 0009_booking_requests
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010_fix_check_names"
down_revision: Union[str, None] = "0009_booking_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# table -> the names after ck_<table>_, as tables.py declares them
CHECKS = {
    "expenses": ["amount_positive", "decided_at_matches_status", "expense_status", "pending_has_no_decider"],
    "time_entries": ["at_most_24_hours", "ends_after_start", "rate_not_negative"],
    "budget_alerts": ["alertable_level", "budget_level"],
}


def _rename(doubled_to_single: bool) -> None:
    for table, names in CHECKS.items():
        for name in names:
            single, doubled = f"ck_{table}_{name}", f"ck_{table}_ck_{table}_{name}"
            old, new = (doubled, single) if doubled_to_single else (single, doubled)
            op.execute(f'ALTER TABLE {table} RENAME CONSTRAINT "{old}" TO "{new}"')


def upgrade() -> None:
    _rename(doubled_to_single=True)


def downgrade() -> None:
    _rename(doubled_to_single=False)
