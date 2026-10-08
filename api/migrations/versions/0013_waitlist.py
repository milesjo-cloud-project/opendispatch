"""launch waitlist: people waiting for Winter 2027, with a spot each

Revision ID: 0013_waitlist
Revises: 0012_calendar_outbox
Create Date: 2026-10-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_waitlist"
down_revision: Union[str, None] = "0012_calendar_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PLANS = ("hosted_monthly", "annual", "perpetual", "self_hosted", "undecided")


def upgrade() -> None:
    # The one table with no company_id: a signup belongs to whoever runs the server, not
    # to a tenant, so none of the (company_id, id) machinery in 0002 applies to it.
    # Names are bare: the naming convention adds the ck_<table>_ prefix.
    op.create_table(
        "waitlist_signups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("spot", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("company", sa.String(200), nullable=True),
        sa.Column("trade", sa.String(100), nullable=True),
        sa.Column("crew_size", sa.String(40), nullable=True),
        sa.Column("plan", sa.String(20), nullable=False),
        sa.Column("current_tool", sa.String(200), nullable=True),
        sa.Column("region", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_waitlist_signups"),
        sa.UniqueConstraint("spot", name="uq_waitlist_signups_spot"),
        sa.CheckConstraint(f"plan IN {PLANS!r}", name="waitlist_plan_interest"),
        sa.CheckConstraint("spot >= 1", name="spot_starts_at_one"),
    )
    # One person, one spot: otherwise Pat@x.com and pat@x.com hold two founding spots
    # and get two launch emails.
    op.execute(
        "CREATE UNIQUE INDEX uq_waitlist_signups_email_lower "
        "ON waitlist_signups (lower(email))"
    )


def downgrade() -> None:
    op.drop_table("waitlist_signups")
