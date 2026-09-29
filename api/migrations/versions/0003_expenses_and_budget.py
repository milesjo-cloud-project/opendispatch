"""expenses and budget: per-company approval limit, quoted amount on jobs, expenses table

Revision ID: 0003_expenses_and_budget
Revises: 0002_tenant_integrity
Create Date: 2026-09-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_expenses_and_budget"
down_revision: Union[str, None] = "0002_tenant_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXPENSE_STATUSES = ("pending", "approved", "rejected")


def upgrade() -> None:
    # --- companies: expenses above this (in cents) need the owner's OK. $500 default.
    op.add_column("companies", sa.Column(
        "expense_approval_limit_cents", sa.Integer(), nullable=False, server_default="50000"
    ))
    op.create_check_constraint(
        op.f("ck_companies_approval_limit_not_negative"), "companies",
        "expense_approval_limit_cents >= 0",
    )

    # --- jobs: what the customer was quoted, in cents. NULL = no quote yet.
    op.add_column("jobs", sa.Column("quoted_amount_cents", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        op.f("ck_jobs_quote_not_negative"), "jobs", "quoted_amount_cents >= 0"
    )

    # --- expenses
    op.create_table(
        "expenses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submitted_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("vendor", sa.String(200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("spent_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_expenses"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name="fk_expenses_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "job_id"], ["jobs.company_id", "jobs.id"],
                                name="fk_expenses_job_same_company"),
        sa.ForeignKeyConstraint(["company_id", "submitted_by_user_id"], ["users.company_id", "users.id"],
                                name="fk_expenses_submitter_same_company"),
        sa.ForeignKeyConstraint(["company_id", "decided_by_user_id"], ["users.company_id", "users.id"],
                                name="fk_expenses_decider_same_company"),
        sa.CheckConstraint(f"status IN {EXPENSE_STATUSES!r}", name="ck_expenses_expense_status"),
        sa.CheckConstraint("amount_cents > 0", name="ck_expenses_amount_positive"),
        sa.CheckConstraint("(status = 'pending') = (decided_at IS NULL)",
                           name="ck_expenses_decided_at_matches_status"),
        sa.CheckConstraint("status <> 'pending' OR decided_by_user_id IS NULL",
                           name="ck_expenses_pending_has_no_decider"),
    )
    op.create_index("ix_expenses_job_id", "expenses", ["job_id"])
    op.create_index("ix_expenses_company_status", "expenses", ["company_id", "status"])


def downgrade() -> None:
    op.drop_table("expenses")
    op.drop_constraint(op.f("ck_jobs_quote_not_negative"), "jobs", type_="check")
    op.drop_column("jobs", "quoted_amount_cents")
    op.drop_constraint(op.f("ck_companies_approval_limit_not_negative"), "companies", type_="check")
    op.drop_column("companies", "expense_approval_limit_cents")
