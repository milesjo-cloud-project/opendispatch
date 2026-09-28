"""Database tables and the mapping from domain dataclasses onto them.

Uses SQLAlchemy "imperative mapping" so domain/ stays free of any database code.
Call start_mappers() once at app startup (and in tests) before using a Session.
"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import registry

from app.domain.entities import Company, Customer, Job, JobEvent, Technician, User
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


def _status_column_type(name: str) -> Enum:
    # Stored as VARCHAR + CHECK constraint (not a native Postgres enum),
    # so adding a status later is an easy migration.
    return Enum(
        JobStatus,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
    )


def _uuid() -> UUID:
    return UUID(as_uuid=True)


def _company_fk() -> Column:
    return Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False, index=True)


def _created_at() -> Column:
    return Column("created_at", DateTime(timezone=True), nullable=False)


companies = Table(
    "companies",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("name", String(200), nullable=False),
    _created_at(),
)

users = Table(
    "users",
    metadata,
    Column("id", _uuid(), primary_key=True),
    _company_fk(),
    Column("email", String(320), nullable=False, unique=True),
    Column("role", String(20), nullable=False),
    _created_at(),
)

technicians = Table(
    "technicians",
    metadata,
    Column("id", _uuid(), primary_key=True),
    _company_fk(),
    Column("user_id", _uuid(), ForeignKey("users.id"), nullable=False, unique=True),
    Column("display_name", String(200), nullable=False),
    Column("phone", String(40)),
    Column("active", Boolean, nullable=False, default=True),
    _created_at(),
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
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False),
    Column("customer_id", _uuid(), ForeignKey("customers.id"), nullable=False, index=True),
    Column("technician_id", _uuid(), ForeignKey("technicians.id"), index=True),
    Column("title", String(200), nullable=False),
    Column("description", Text),
    Column("status", _status_column_type("job_status"), nullable=False),
    Column("scheduled_start", DateTime(timezone=True)),
    _created_at(),
    Index("ix_jobs_company_status", "company_id", "status"),
)

job_events = Table(
    "job_events",
    metadata,
    Column("id", _uuid(), primary_key=True),
    Column("job_id", _uuid(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("company_id", _uuid(), ForeignKey("companies.id"), nullable=False, index=True),
    Column("from_status", _status_column_type("job_event_from_status")),
    Column("to_status", _status_column_type("job_event_to_status"), nullable=False),
    Column("actor_user_id", _uuid(), ForeignKey("users.id")),
    Column("note", Text),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
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
    ]:
        mapper_registry.map_imperatively(cls, table)
    _mapped = True
