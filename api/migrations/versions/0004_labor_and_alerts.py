"""labor and alerts: technician hourly rate, time_entries, budget_alerts outbox

Revision ID: 0004_labor_and_alerts
Revises: 0003_expenses_and_budget
Create Date: 2026-09-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_labor_and_alerts"
down_revision: Union[str, None] = "0003_expenses_and_budget"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BUDGET_LEVELS = ("no_quote", "ok", "warning", "over")


def upgrade() -> None:
    # --- technicians: what an hour of their time costs the company, in cents
    op.add_column("technicians", sa.Column("hourly_rate_cents", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_technicians_rate_not_negative"), "technicians", "hourly_rate_cents >= 0"
    )

    # --- time_entries
    op.create_table(
        "time_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("technician_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hourly_rate_cents", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_time_entries"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                name="fk_time_entries_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "job_id"], ["jobs.company_id", "jobs.id"],
                                name="fk_time_entries_job_same_company"),
        sa.ForeignKeyConstraint(["company_id", "technician_id"],
                                ["technicians.company_id", "technicians.id"],
                                name="fk_time_entries_technician_same_company"),
        sa.CheckConstraint("ended_at > started_at", name="ck_time_entries_ends_after_start"),
        sa.CheckConstraint("ended_at - started_at <= interval '24 hours'",
                           name="ck_time_entries_at_most_24_hours"),
        sa.CheckConstraint("hourly_rate_cents >= 0", name="ck_time_entries_rate_not_negative"),
    )
    op.create_index("ix_time_entries_job_id", "time_entries", ["job_id"])
    op.create_index("ix_time_entries_technician_id", "time_entries", ["technician_id"])

    # --- budget_alerts: one per job per level, sent after the spend that caused it commits
    op.create_table(
        "budget_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("quoted_cents", sa.BigInteger(), nullable=False),
        sa.Column("spent_cents", sa.BigInteger(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_budget_alerts"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                name="fk_budget_alerts_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "job_id"], ["jobs.company_id", "jobs.id"],
                                name="fk_budget_alerts_job_same_company"),
        sa.UniqueConstraint("job_id", "level", name="uq_budget_alerts_job_id_level"),
        sa.CheckConstraint(f"level IN {BUDGET_LEVELS!r}", name="ck_budget_alerts_budget_level"),
        sa.CheckConstraint("level IN ('warning', 'over')", name="ck_budget_alerts_alertable_level"),
    )
    op.create_index("ix_budget_alerts_unsent", "budget_alerts", ["created_at"],
                    postgresql_where=sa.text("sent_at IS NULL"))


def downgrade() -> None:
    op.drop_table("budget_alerts")
    op.drop_table("time_entries")
    op.drop_constraint(op.f("ck_technicians_rate_not_negative"), "technicians", type_="check")
    op.drop_column("technicians", "hourly_rate_cents")
