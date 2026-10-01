"""auth and sms: user passwords, phone, lockout; login sessions; company SMS alert switch

Revision ID: 0005_auth_and_sms
Revises: 0004_labor_and_alerts
Create Date: 2026-09-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_auth_and_sms"
down_revision: Union[str, None] = "0004_labor_and_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- companies: texting alerts costs money, so it's off until the owner turns it on
    op.add_column("companies", sa.Column(
        "sms_alerts_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
    ))

    # --- users: login and where SMS alerts go. Existing users have no password until one is set.
    op.add_column("users", sa.Column("phone", sa.String(16), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_users_phone_e164"), "users", r"phone ~ '^\+[1-9][0-9]{7,14}$'"
    )

    # --- auth_sessions: one row per logged-in device; only the token's SHA-256 is stored
    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                name="fk_auth_sessions_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "user_id"], ["users.company_id", "users.id"],
                                name="fk_auth_sessions_user_same_company"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_table("auth_sessions")
    op.drop_constraint(op.f("ck_users_phone_e164"), "users", type_="check")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_logins")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "phone")
    op.drop_column("companies", "sms_alerts_enabled")
