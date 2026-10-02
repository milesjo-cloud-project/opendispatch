"""Company settings, people, and customers. Everything is scoped to the caller's company."""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Actor, current_actor, get_hasher, get_session, office_actor, owner_actor
from app.api.schemas import (
    CompanyOut,
    CompanyUpdate,
    CustomerCreate,
    CustomerOut,
    TechnicianCreate,
    TechnicianOut,
    TechnicianUpdate,
    UserCreate,
    UserOut,
)
from app.domain.access import is_owner
from app.domain.entities import Company, Customer, Technician, User
from app.domain.errors import DomainRuleViolation
from app.ports.passwords import PasswordHasherPort
from app.services import auth
from app.services.spend import NotFound

router = APIRouter()


def _in_company(session: Session, cls, id_: UUID, actor: Actor):
    """Load a row of the caller's company. Another company's row is reported as not found."""
    obj = session.get(cls, id_)
    if obj is None or obj.company_id != actor.user.company_id:
        raise NotFound(f"{cls.__name__} {id_}")
    return obj


# --- company

@router.get("/company", response_model=CompanyOut, tags=["company"])
def get_company(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    return session.get(Company, actor.user.company_id)


@router.patch("/company", response_model=CompanyOut, tags=["company"])
def update_company(body: CompanyUpdate, actor: Actor = Depends(owner_actor),
                   session: Session = Depends(get_session)):
    """Owner only. Change the name, the expense approval limit, or turn SMS alerts on/off."""
    company = session.get(Company, actor.user.company_id)
    if body.name is not None:
        company.name = body.name.strip()
    if body.expense_approval_limit_cents is not None:
        company.set_approval_limit(body.expense_approval_limit_cents)
    if body.sms_alerts_enabled is not None:
        company.sms_alerts_enabled = body.sms_alerts_enabled
    session.commit()
    return company


# --- users

@router.get("/users", response_model=list[UserOut], tags=["people"])
def list_users(actor: Actor = Depends(office_actor), session: Session = Depends(get_session)):
    return session.scalars(
        select(User).where(User.company_id == actor.user.company_id).order_by(User.email)
    ).all()


@router.post("/users", response_model=UserOut, status_code=201, tags=["people"])
def create_user(body: UserCreate, actor: Actor = Depends(owner_actor),
                session: Session = Depends(get_session),
                hasher: PasswordHasherPort = Depends(get_hasher)):
    """Owner only. Add a dispatcher, technician or another owner with a starting password."""
    user = auth.create_user(session, hasher, company_id=actor.user.company_id, email=body.email,
                            role=body.role, password=body.password, phone=body.phone)
    session.commit()
    return user


@router.post("/users/{user_id}/disable", response_model=UserOut, tags=["people"])
def disable_user(user_id: UUID, actor: Actor = Depends(owner_actor), session: Session = Depends(get_session)):
    """Owner only. Sign someone out everywhere and stop them signing in, e.g. when they leave.
    Their jobs and history stay. Not your own account."""
    user = _in_company(session, User, user_id, actor)
    auth.disable_user(session, by=actor.user, user=user)
    session.commit()
    return user


@router.post("/users/{user_id}/enable", response_model=UserOut, tags=["people"])
def enable_user(user_id: UUID, actor: Actor = Depends(owner_actor), session: Session = Depends(get_session)):
    """Owner only. Let a disabled user sign in again. Put their technician profile back on
    the schedule separately (PATCH /technicians/{id} with active: true)."""
    user = _in_company(session, User, user_id, actor)
    auth.enable_user(user)
    session.commit()
    return user


# --- technicians

def _tech_out(tech: Technician, actor: Actor) -> TechnicianOut:
    out = TechnicianOut.model_validate(tech)
    if not is_owner(actor.user):
        out.hourly_rate_cents = None  # pay is the owner's business
    return out


@router.get("/technicians", response_model=list[TechnicianOut], tags=["people"])
def list_technicians(actor: Actor = Depends(office_actor), session: Session = Depends(get_session)):
    techs = session.scalars(
        select(Technician).where(Technician.company_id == actor.user.company_id)
        .order_by(Technician.display_name)
    ).all()
    return [_tech_out(t, actor) for t in techs]


@router.post("/technicians", response_model=TechnicianOut, status_code=201, tags=["people"])
def create_technician(body: TechnicianCreate, actor: Actor = Depends(owner_actor),
                      session: Session = Depends(get_session)):
    """Owner only. Give a user a technician profile so jobs can be assigned to them."""
    user = _in_company(session, User, body.user_id, actor)
    if session.scalars(select(Technician).where(Technician.user_id == user.id)).first():
        raise DomainRuleViolation("That user already has a technician profile")
    tech = Technician(company_id=user.company_id, user_id=user.id, display_name=body.display_name,
                      phone=body.phone, hourly_rate_cents=body.hourly_rate_cents)
    session.add(tech)
    session.commit()
    return _tech_out(tech, actor)


@router.patch("/technicians/{technician_id}", response_model=TechnicianOut, tags=["people"])
def update_technician(technician_id: UUID, body: TechnicianUpdate,
                      actor: Actor = Depends(owner_actor), session: Session = Depends(get_session)):
    """Owner only. Change name, phone, active, or hourly rate (past time keeps its old rate)."""
    tech = _in_company(session, Technician, technician_id, actor)
    sent = body.model_fields_set
    if "display_name" in sent and body.display_name is not None:
        tech.display_name = body.display_name
    if "phone" in sent:
        tech.phone = body.phone
    if "active" in sent and body.active is not None:
        tech.active = body.active
    if "hourly_rate_cents" in sent:
        tech.set_hourly_rate(body.hourly_rate_cents)
    session.commit()
    return _tech_out(tech, actor)


# --- customers

@router.get("/customers", response_model=list[CustomerOut], tags=["customers"])
def list_customers(actor: Actor = Depends(office_actor), session: Session = Depends(get_session)):
    return session.scalars(
        select(Customer).where(Customer.company_id == actor.user.company_id).order_by(Customer.name)
    ).all()


@router.post("/customers", response_model=CustomerOut, status_code=201, tags=["customers"])
def create_customer(body: CustomerCreate, actor: Actor = Depends(office_actor),
                    session: Session = Depends(get_session)):
    customer = Customer(company_id=actor.user.company_id, **body.model_dump())
    session.add(customer)
    session.commit()
    return customer
