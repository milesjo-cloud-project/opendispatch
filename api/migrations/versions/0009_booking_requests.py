"""online booking: a public booking id per company, the requests customers send, per-IP limits

Revision ID: 0009_booking_requests
Revises: 0008_user_disable
Create Date: 2026-10-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_booking_requests"
down_revision: Union[str, None] = "0008_user_disable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUSES = ("new", "accepted", "declined")


def upgrade() -> None:
    # NULL = booking off. No company gets a public link until its owner turns one on.
    op.add_column("companies", sa.Column("booking_id", sa.String(16), nullable=True))
    op.create_unique_constraint("uq_companies_booking_id", "companies", ["booking_id"])

    # Names are bare: the naming convention adds the ck_<table>_ prefix.
    op.create_table(
        "booking_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("preferred_time", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_booking_requests"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                name="fk_booking_requests_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "job_id"], ["jobs.company_id", "jobs.id"],
                                name="fk_booking_requests_job_same_company"),
        sa.ForeignKeyConstraint(["company_id", "decided_by_user_id"], ["users.company_id", "users.id"],
                                name="fk_booking_requests_decider_same_company"),
        sa.UniqueConstraint("job_id", name="uq_booking_requests_job_id"),
        sa.CheckConstraint(f"status IN {STATUSES!r}", name="booking_request_status"),
        sa.CheckConstraint("phone IS NOT NULL OR email IS NOT NULL", name="has_contact"),
        sa.CheckConstraint("(status = 'accepted') = (job_id IS NOT NULL)", name="job_matches_status"),
        sa.CheckConstraint("(status = 'new') = (decided_at IS NULL)", name="decided_at_matches_status"),
    )
    # The office inbox asks for one company's new requests
    op.create_index("ix_booking_requests_company_status", "booking_requests", ["company_id", "status"])

    # Per-IP limits on the public form; not per company on purpose (see tables.py)
    op.create_table(
        "rate_limit_hits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bucket", sa.String(40), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_rate_limit_hits"),
    )
    op.create_index("ix_rate_limit_hits_bucket_key_created", "rate_limit_hits",
                    ["bucket", "key_hash", "created_at"])


def downgrade() -> None:
    op.drop_table("rate_limit_hits")
    op.drop_table("booking_requests")
    op.drop_constraint("uq_companies_booking_id", "companies", type_="unique")
    op.drop_column("companies", "booking_id")
