"""private customer tracking links and job attachments

Revision ID: 0007_tracking_and_attachments
Revises: 0006_password_reset
Create Date: 2026-09-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_tracking_and_attachments"
down_revision: Union[str, None] = "0006_password_reset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="size_positive"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                name="fk_job_attachments_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "job_id"], ["jobs.company_id", "jobs.id"],
                                name="fk_job_attachments_job_same_company"),
        sa.ForeignKeyConstraint(["company_id", "uploaded_by_user_id"], ["users.company_id", "users.id"],
                                name="fk_job_attachments_uploader_same_company"),
        sa.PrimaryKeyConstraint("id", name="pk_job_attachments"),
        sa.UniqueConstraint("storage_key", name="uq_job_attachments_storage_key"),
    )
    op.create_index("ix_job_attachments_company_id", "job_attachments", ["company_id"])
    op.create_index("ix_job_attachments_job_id", "job_attachments", ["job_id"])

    op.create_table(
        "job_tracking_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                name="fk_job_tracking_links_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "job_id"], ["jobs.company_id", "jobs.id"],
                                name="fk_job_tracking_links_job_same_company"),
        sa.PrimaryKeyConstraint("id", name="pk_job_tracking_links"),
        sa.UniqueConstraint("token_hash", name="uq_job_tracking_links_token_hash"),
    )
    op.create_index("ix_job_tracking_links_company_id", "job_tracking_links", ["company_id"])
    op.create_index("ix_job_tracking_links_job_id", "job_tracking_links", ["job_id"])


def downgrade() -> None:
    op.drop_table("job_tracking_links")
    op.drop_table("job_attachments")
