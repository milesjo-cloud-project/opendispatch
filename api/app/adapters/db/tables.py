"""Database tables and the mapping from domain dataclasses onto them.

Uses SQLAlchemy "imperative mapping" so domain/ stays free of any database code.
Call start_mappers() once at app startup (and in tests) before using a Session.
"""
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import registry

from app.domain.auth import AuthSession, PasswordResetToken
from app.domain.booking import BookingRequest, BookingRequestStatus
from app.domain.budget import BudgetAlert, BudgetLevel
from app.domain.entities import (
    DEFAULT_EXPENSE_APPROVAL_LIMIT_CENTS,
    Company,
    Customer,
    Expense,
    ExpenseStatus,
    Job,
    JobAttachment,
    JobEvent,
    Technician,
    TimeEntry,
    User,
    UserRole,
)
from app.domain.job_status import JobStatus

# Stable constraint names, so migrations and downgrades don't break.
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)
mapper_registry = registry(metadata=metadata)


def _enum_type(enum_cls, name: str) -> Enum:
    # Stored as VARCHAR + CHECK constraint (not a native Postgres enum),
    # so adding a value later is an easy migration.
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
    )


def _status_column_type(name: str) -> Enum:
    return _enum_type(JobStatus, name)


def _uuid() -> UUID:
    return UUID(as_uuid=True)


def _company_fk() -> Column:
    return Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False, index=True)


def _created_at() -> Column:
    return Column("created_at", DateTime(timezone=True), nullable=False)


def _company_scoped_key(table: str) -> UniqueConstraint:
    # Lets other tables point at (company_id, id), so a reference can't cross companies.
    return UniqueConstraint("company_id", "id", name=f"uq_{table}_company_id_id")


def _same_company_fk(name: str, column: str, target: str) -> ForeignKeyConstraint:
    """FK on (company_id, column) -> target(company_id, id).

    A job can only point at a customer/technician/user in its own company.
    When `column` is NULL the constraint is skipped (Postgres MATCH SIMPLE).
    """
    return ForeignKeyConstraint(
        ["company_id", column], [f"{target}.company_id", f"{target}.id"], name=name
    )


companies = Table(
    "companies",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("name", String(200), nullable=False),
    # Cents. Expenses above this wait for the owner.
    Column("expense_approval_limit_cents", Integer, nullable=False,
           server_default=str(DEFAULT_EXPENSE_APPROVAL_LIMIT_CENTS)),
    Column("sms_alerts_enabled", Boolean, nullable=False, server_default="false"),
    Column("booking_id", String(16), unique=True),  # NULL = online booking off
    _created_at(),
    CheckConstraint("expense_approval_limit_cents >= 0", name="approval_limit_not_negative"),
)

users = Table(
    "users",
    metadata,
    Column("id", _uuid(), primary_key=True),
    _company_fk(),
    Column("email", String(320), nullable=False),
    Column("role", _enum_type(UserRole, "user_role"), nullable=False),
    Column("phone", String(16)),
    Column("password_hash", String(255)),
    Column("failed_logins", Integer, nullable=False, server_default="0"),
    Column("locked_until", DateTime(timezone=True)),
    Column("disabled_at", DateTime(timezone=True)),
    _created_at(),
    CheckConstraint(r"phone ~ '^\+[1-9][0-9]{7,14}$'", name="phone_e164"),
    _company_scoped_key("users"),
)
# Case-insensitive: Bob@x.com and bob@x.com can't be two accounts.
Index("uq_users_email_lower", func.lower(users.c.email), unique=True)

technicians = Table(
    "technicians",
    metadata,
    Column("id", _uuid(), primary_key=True),
    _company_fk(),
    Column("user_id", _uuid(), nullable=False, unique=True),
    Column("display_name", String(200), nullable=False),
    Column("phone", String(40)),
    Column("active", Boolean, nullable=False, default=True),
    Column("hourly_rate_cents", Integer),
    _created_at(),
    CheckConstraint("hourly_rate_cents >= 0", name="rate_not_negative"),
    _company_scoped_key("technicians"),
    _same_company_fk("fk_technicians_user_same_company", "user_id", "users"),
)

customers = Table(
    "customers",
    metadata,
    Column("id", _uuid(), primary_key=True),
    _company_fk(),
    Column("name", String(200), nullable=False),
    Column("phone", String(40)),
    Column("email", String(320)),
    Column("address", Text),
    _created_at(),
    _company_scoped_key("customers"),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False),
    Column("customer_id", _uuid(), nullable=False, index=True),
    Column("technician_id", _uuid(), index=True),
    Column("title", String(200), nullable=False),
    Column("description", Text),
    Column("status", _status_column_type("job_status"), nullable=False),
    Column("scheduled_start", DateTime(timezone=True)),
    Column("quoted_amount_cents", BigInteger),
    _created_at(),
    CheckConstraint("quoted_amount_cents >= 0", name="quote_not_negative"),
    Index("ix_jobs_company_status", "company_id", "status"),
    _company_scoped_key("jobs"),
    _same_company_fk("fk_jobs_customer_same_company", "customer_id", "customers"),
    _same_company_fk("fk_jobs_technician_same_company", "technician_id", "technicians"),
)

# Append-only: migration 0002 adds a trigger that rejects UPDATE, DELETE and TRUNCATE,
# and a job with history can't be deleted (no cascade).
job_events = Table(
    "job_events",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("job_id", _uuid(), nullable=False, index=True),
    Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False, index=True),
    Column("from_status", _status_column_type("job_event_from_status")),
    Column("to_status", _status_column_type("job_event_to_status"), nullable=False),
    Column("actor_user_id", _uuid()),
    Column("note", Text),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    _same_company_fk("fk_job_events_job_same_company", "job_id", "jobs"),
    _same_company_fk("fk_job_events_actor_same_company", "actor_user_id", "users"),
)

job_attachments = Table(
    "job_attachments",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False, index=True),
    Column("job_id", _uuid(), nullable=False, index=True),
    Column("uploaded_by_user_id", _uuid(), nullable=False),
    Column("filename", String(255), nullable=False),
    Column("content_type", String(120), nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("storage_key", String(64), nullable=False, unique=True),
    _created_at(),
    CheckConstraint("size_bytes > 0", name="size_positive"),
    _same_company_fk("fk_job_attachments_job_same_company", "job_id", "jobs"),
    _same_company_fk("fk_job_attachments_uploader_same_company", "uploaded_by_user_id", "users"),
)

job_tracking_links = Table(
    "job_tracking_links",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False, index=True),
    Column("job_id", _uuid(), nullable=False, index=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    _created_at(),
    _same_company_fk("fk_job_tracking_links_job_same_company", "job_id", "jobs"),
)

# What customers send through the public booking link. Nothing here points at a customer:
# the office picks one when it accepts, and only then does a job (job_id) exist.
booking_requests = Table(
    "booking_requests",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False),
    Column("name", String(200), nullable=False),
    Column("phone", String(40)),
    Column("email", String(320)),
    Column("address", Text),
    Column("title", String(200), nullable=False),
    Column("description", Text),
    Column("preferred_time", String(200)),
    Column("status", _enum_type(BookingRequestStatus, "booking_request_status"), nullable=False),
    Column("job_id", _uuid(), unique=True),  # one request makes at most one job
    Column("decided_by_user_id", _uuid()),
    Column("decided_at", DateTime(timezone=True)),
    _created_at(),
    Index("ix_booking_requests_company_status", "company_id", "status"),
    CheckConstraint("phone IS NOT NULL OR email IS NOT NULL", name="has_contact"),
    CheckConstraint("(status = 'accepted') = (job_id IS NOT NULL)", name="job_matches_status"),
    CheckConstraint("(status = 'new') = (decided_at IS NULL)", name="decided_at_matches_status"),
    _same_company_fk("fk_booking_requests_job_same_company", "job_id", "jobs"),
    _same_company_fk("fk_booking_requests_decider_same_company", "decided_by_user_id", "users"),
)

# One row per counted request, for per-IP limits on public routes. Deliberately NOT per
# company: one spammer is one spammer across every company's link. key_hash is a SHA-256 so
# addresses aren't stored as plain text, but that's not anonymous (IPv4 is easy to brute
# force); what protects them is that rows older than the window are deleted on the next hit.
rate_limit_hits = Table(
    "rate_limit_hits",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("bucket", String(40), nullable=False),  # what's limited, e.g. "booking"
    Column("key_hash", String(64), nullable=False),
    _created_at(),
    Index("ix_rate_limit_hits_bucket_key_created", "bucket", "key_hash", "created_at"),
)

# A decision (approved/rejected) always has a time; a pending expense never does.
# decided_by_user_id is NULL when an expense was approved automatically.
expenses = Table(
    "expenses",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False),
    Column("job_id", _uuid(), nullable=False, index=True),
    Column("submitted_by_user_id", _uuid(), nullable=False),
    Column("amount_cents", BigInteger, nullable=False),
    Column("vendor", String(200)),
    Column("description", Text),
    Column("spent_on", Date),
    Column("status", _enum_type(ExpenseStatus, "expense_status"), nullable=False),
    Column("decided_by_user_id", _uuid()),
    Column("decided_at", DateTime(timezone=True)),
    Column("decision_note", Text),
    _created_at(),
    Index("ix_expenses_company_status", "company_id", "status"),
    CheckConstraint("amount_cents > 0", name="amount_positive"),
    CheckConstraint("(status = 'pending') = (decided_at IS NULL)", name="decided_at_matches_status"),
    CheckConstraint("status <> 'pending' OR decided_by_user_id IS NULL", name="pending_has_no_decider"),
    _same_company_fk("fk_expenses_job_same_company", "job_id", "jobs"),
    _same_company_fk("fk_expenses_submitter_same_company", "submitted_by_user_id", "users"),
    _same_company_fk("fk_expenses_decider_same_company", "decided_by_user_id", "users"),
)

# The rate is copied from the technician when time is logged, so raises don't rewrite history.
time_entries = Table(
    "time_entries",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False),
    Column("job_id", _uuid(), nullable=False, index=True),
    Column("technician_id", _uuid(), nullable=False, index=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("ended_at", DateTime(timezone=True), nullable=False),
    Column("hourly_rate_cents", Integer, nullable=False),
    Column("note", Text),
    _created_at(),
    CheckConstraint("ended_at > started_at", name="ends_after_start"),
    CheckConstraint("ended_at - started_at <= interval '24 hours'", name="at_most_24_hours"),
    CheckConstraint("hourly_rate_cents >= 0", name="rate_not_negative"),
    _same_company_fk("fk_time_entries_job_same_company", "job_id", "jobs"),
    _same_company_fk("fk_time_entries_technician_same_company", "technician_id", "technicians"),
)

# Doubles as an outbox: rows are written with the spend that caused them and
# sent afterwards. The unique key means each job warns once and goes over once.
budget_alerts = Table(
    "budget_alerts",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False),
    Column("job_id", _uuid(), nullable=False),
    Column("level", _enum_type(BudgetLevel, "budget_level"), nullable=False),
    Column("quoted_cents", BigInteger, nullable=False),
    Column("spent_cents", BigInteger, nullable=False),
    Column("sent_at", DateTime(timezone=True)),
    _created_at(),
    UniqueConstraint("job_id", "level", name="uq_budget_alerts_job_id_level"),
    CheckConstraint("level IN ('warning', 'over')", name="alertable_level"),
    _same_company_fk("fk_budget_alerts_job_same_company", "job_id", "jobs"),
)
Index("ix_budget_alerts_unsent", budget_alerts.c.created_at,
      postgresql_where=budget_alerts.c.sent_at.is_(None))

# Only a SHA-256 of each token is stored, so a leaked table can't be used to log in.
auth_sessions = Table(
    "auth_sessions",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False),
    Column("user_id", _uuid(), nullable=False, index=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    _created_at(),
    _same_company_fk("fk_auth_sessions_user_same_company", "user_id", "users"),
)

password_reset_tokens = Table(
    "password_reset_tokens",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False),
    Column("user_id", _uuid(), nullable=False, index=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
    _created_at(),
    _same_company_fk("fk_password_reset_tokens_user_same_company", "user_id", "users"),
)

_mapped = False


def start_mappers() -> None:
    """Attach the domain classes to their tables. Safe to call more than once."""
    global _mapped
    if _mapped:
        return
    for cls, table in [
        (Company, companies),
        (User, users),
        (Technician, technicians),
        (Customer, customers),
        (Job, jobs),
        (JobEvent, job_events),
        (JobAttachment, job_attachments),
        (BookingRequest, booking_requests),
        (Expense, expenses),
        (TimeEntry, time_entries),
        (BudgetAlert, budget_alerts),
        (AuthSession, auth_sessions),
        (PasswordResetToken, password_reset_tokens),
    ]:
        mapper_registry.map_imperatively(cls, table)
    _mapped = True
