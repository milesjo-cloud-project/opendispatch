"""calendar outbox and the event each job has

Calendar writes are queued in calendar_outbox and done after the job's transaction
commits, so a provider that's down delays an event instead of failing a dispatcher's
save. A row carries no payload, only "this job's event is out of date", and the partial
unique index keeps it to one pending row per job. job_calendar_events remembers the
provider's id for the event a job currently has.

Revision ID: 0012_calendar_outbox
Revises: 0011_login_failures
Create Date: 2026-10-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_calendar_outbox"
down_revision: Union[str, None] = "0011_login_failures"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendar_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        sa.PrimaryKeyConstraint("id", name="pk_calendar_outbox"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                name="fk_calendar_outbox_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "job_id"], ["jobs.company_id", "jobs.id"],
                                name="fk_calendar_outbox_job_same_company"),
    )
    op.create_index("ix_calendar_outbox_company_id", "calendar_outbox", ["company_id"])
    op.create_index("uq_calendar_outbox_pending_job", "calendar_outbox", ["job_id"],
                    unique=True, postgresql_where=sa.text("sent_at IS NULL"))
    op.create_index("ix_calendar_outbox_due", "calendar_outbox", ["next_attempt_at"],
                    postgresql_where=sa.text("sent_at IS NULL"))

    op.create_table(
        "job_calendar_events",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("job_id", name="pk_job_calendar_events"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                name="fk_job_calendar_events_company_id_companies"),
        sa.ForeignKeyConstraint(["company_id", "job_id"], ["jobs.company_id", "jobs.id"],
                                name="fk_job_calendar_events_job_same_company"),
    )
    op.create_index("ix_job_calendar_events_company_id", "job_calendar_events", ["company_id"])


def downgrade() -> None:
    op.drop_table("job_calendar_events")
    op.drop_table("calendar_outbox")
