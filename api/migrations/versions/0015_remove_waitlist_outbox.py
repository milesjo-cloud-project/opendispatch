"""Remove the launch waitlist's deferred spreadsheet export queue.

Revision ID: 0015_remove_waitlist_outbox
Revises: 0014_waitlist_outbox
Create Date: 2026-10-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_remove_waitlist_outbox"
down_revision: Union[str, None] = "0014_waitlist_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("waitlist_outbox")


def downgrade() -> None:
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
        sa.ForeignKeyConstraint(
            ["signup_id"], ["waitlist_signups.id"],
            name="fk_waitlist_outbox_signup_id_waitlist_signups", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_waitlist_outbox"),
    )
    op.create_index("uq_waitlist_outbox_pending_signup", "waitlist_outbox", ["signup_id"],
                    unique=True, postgresql_where=sa.text("sent_at IS NULL"))
    op.create_index("ix_waitlist_outbox_due", "waitlist_outbox", ["next_attempt_at"],
                    postgresql_where=sa.text("sent_at IS NULL"))
