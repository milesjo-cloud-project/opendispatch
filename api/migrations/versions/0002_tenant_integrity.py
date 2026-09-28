"""tenant integrity: same-company foreign keys, user role check, case-insensitive email,
append-only job_events

Revision ID: 0002_tenant_integrity
Revises: 0001_initial
Create Date: 2026-09-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_tenant_integrity"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLES = ("owner", "dispatcher", "technician")

# (table, name, column, target, old single-column FK name, old FK ondelete)
SAME_COMPANY_FKS = [
    ("technicians", "fk_technicians_user_same_company", "user_id", "users",
     "fk_technicians_user_id_users", None),
    ("jobs", "fk_jobs_customer_same_company", "customer_id", "customers",
     "fk_jobs_customer_id_customers", None),
    ("jobs", "fk_jobs_technician_same_company", "technician_id", "technicians",
     "fk_jobs_technician_id_technicians", None),
    ("job_events", "fk_job_events_job_same_company", "job_id", "jobs",
     "fk_job_events_job_id_jobs", "CASCADE"),
    ("job_events", "fk_job_events_actor_same_company", "actor_user_id", "users",
     "fk_job_events_actor_user_id_users", None),
]


def upgrade() -> None:
    # --- users: role must be a known value; email unique regardless of case
    op.create_check_constraint(
        op.f("ck_users_user_role"), "users", f"role IN {ROLES!r}"
    )
    op.execute("UPDATE users SET email = lower(trim(email))")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    # --- (company_id, id) keys that same-company FKs can point at
    for table in ("users", "technicians", "customers", "jobs"):
        op.create_unique_constraint(f"uq_{table}_company_id_id", table, ["company_id", "id"])

    # --- swap single-column FKs for (company_id, x) FKs.
    # job_events loses ON DELETE CASCADE: a job with history can't be deleted.
    for table, name, column, target, old_name, _ in SAME_COMPANY_FKS:
        op.drop_constraint(old_name, table, type_="foreignkey")
        op.create_foreign_key(name, table, target, ["company_id", column], ["company_id", "id"])

    # --- job_events is append-only, enforced by Postgres itself
    op.execute("""
        CREATE FUNCTION job_events_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'job_events is append-only (% blocked)', TG_OP;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER job_events_no_update_delete
        BEFORE UPDATE OR DELETE ON job_events
        FOR EACH ROW EXECUTE FUNCTION job_events_append_only()
    """)
    op.execute("""
        CREATE TRIGGER job_events_no_truncate
        BEFORE TRUNCATE ON job_events
        FOR EACH STATEMENT EXECUTE FUNCTION job_events_append_only()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER job_events_no_truncate ON job_events")
    op.execute("DROP TRIGGER job_events_no_update_delete ON job_events")
    op.execute("DROP FUNCTION job_events_append_only()")

    for table, name, column, target, old_name, ondelete in reversed(SAME_COMPANY_FKS):
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(old_name, table, target, [column], ["id"], ondelete=ondelete)

    for table in ("jobs", "customers", "technicians", "users"):
        op.drop_constraint(f"uq_{table}_company_id_id", table, type_="unique")

    op.drop_index("uq_users_email_lower", "users")
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.drop_constraint(op.f("ck_users_user_role"), "users", type_="check")
