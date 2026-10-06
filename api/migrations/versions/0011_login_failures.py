"""lock sign-in per account and address

Wrong passwords are counted per account AND address, so a stranger who knows an owner's
email can lock out only their own address, not the owner. users.failed_logins stays as the
whole-account backstop (with a much higher limit, in code).

Revision ID: 0011_login_failures
Revises: 0010_fix_check_names
Create Date: 2026-10-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_login_failures"
down_revision: Union[str, None] = "0010_fix_check_names"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_failures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("address_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_login_failures"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                name="fk_login_failures_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "user_id"], ["users.company_id", "users.id"],
                                name="fk_login_failures_user_same_company"),
    )
    op.create_index("ix_login_failures_user_address_created", "login_failures",
                    ["user_id", "address_hash", "created_at"])


def downgrade() -> None:
    op.drop_table("login_failures")
