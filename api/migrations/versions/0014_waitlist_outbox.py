"""queued copies of waitlist signups into the launch spreadsheet

Same shape as calendar_outbox (0012) and the same reason for existing: the write to
Google happens after the signup has committed, so a spreadsheet that's unreachable delays
a row instead of failing somebody's signup. No company_id, because a waitlist signup has
none. A row carries no cells, only "this signup isn't in the sheet yet"; the cells are
rebuilt from the signup when the write goes out.

Revision ID: 0014_waitlist_outbox
Revises: 0013_waitlist
Create Date: 2026-10-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_waitlist_outbox"
down_revision: Union[str, None] = "0013_waitlist"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "waitlist_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signup_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        sa.PrimaryKeyConstraint("id", name="pk_waitlist_outbox"),
        # Deleting a signup (a removal request before launch) takes its queued copy with
        # it. The row already in the sheet is the owner's to clear; nothing here can.
        sa.ForeignKeyConstraint(["signup_id"], ["waitlist_signups.id"],
                                name="fk_waitlist_outbox_signup_id_waitlist_signups",
                                ondelete="CASCADE"),
    )
    op.create_index("uq_waitlist_outbox_pending_signup", "waitlist_outbox", ["signup_id"],
                    unique=True, postgresql_where=sa.text("sent_at IS NULL"))
    op.create_index("ix_waitlist_outbox_due", "waitlist_outbox", ["next_attempt_at"],
                    postgresql_where=sa.text("sent_at IS NULL"))


def downgrade() -> None:
    op.drop_table("waitlist_outbox")
