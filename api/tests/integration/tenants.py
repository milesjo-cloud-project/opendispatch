"""Two-company test data shared by the integration tests. The `a` and `b` fixtures
that build it live in conftest.py, so pytest finds them without imports."""
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.entities import Company, Customer, Job, Technician, User


@dataclass
class Tenant:
    company: Company
    owner: User
    tech: Technician
    customer: Customer


def make_tenant(session, name: str) -> Tenant:
    company = Company(name=name)
    owner = User(company_id=company.id, email=f"owner-{company.id}@example.com", role="owner")
    tech_user = User(company_id=company.id, email=f"tech-{company.id}@example.com", role="technician")
    tech = Technician(company_id=company.id, user_id=tech_user.id, display_name="Sam")
    customer = Customer(company_id=company.id, name="Jane Doe")
    session.add(company)
    session.flush()
    session.add_all([owner, tech_user])
    session.flush()
    session.add_all([tech, customer])
    session.flush()
    return Tenant(company, owner, tech, customer)


def make_job(t: Tenant, **overrides) -> Job:
    fields = dict(company_id=t.company.id, customer_id=t.customer.id, title="Leak",
                  technician_id=t.tech.id,
                  scheduled_start=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc))
    fields.update(overrides)
    return Job(**fields)
