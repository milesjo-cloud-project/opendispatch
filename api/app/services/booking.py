"""Use cases for online booking. The API calls these; they call the domain. The caller commits.

Owner: turn the public /book/<booking_id> link on, replace it, or turn it off.
Public: send a request through the link. It's only a message, so nothing else is touched.
Office: accept a request (link or create the customer, and make a Requested job) or decline it.
Scheduling an accepted job is the normal "Schedule job" flow; this module doesn't repeat it.
"""
import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.job_repository import CustomerRepository, JobRepository
from app.domain.booking import BookingRequest, BookingRequestStatus
from app.domain.entities import Company, Customer, Job, JobEvent, User
from app.domain.errors import DomainRuleViolation
from app.domain.job_status import JobStatus
from app.services.spend import NotFound

BOOKED_ONLINE = "Booked online"


# --- owner: the link

def turn_on(company: Company) -> str:
    """Give the company a new booking id, replacing any old one (whose link then stops working)."""
    company.booking_id = secrets.token_urlsafe(9)  # 12 characters, short enough for a flyer
    return company.booking_id


def turn_off(company: Company) -> None:
    company.booking_id = None


# --- public: no login

def company_for_booking_id(session: Session, booking_id: str) -> Company:
    """The company behind a public link. A wrong id and booking turned off look the same."""
    company = session.scalars(
        select(Company).where(Company.booking_id == booking_id)
    ).one_or_none() if booking_id else None
    if company is None:
        raise NotFound("Booking link")
    return company


def submit(session: Session, booking_id: str, **fields) -> BookingRequest:
    """Save what the customer sent. No customer or job is created or looked up."""
    company = company_for_booking_id(session, booking_id)
    request = BookingRequest(company_id=company.id, **fields)
    session.add(request)
    session.flush()
    return request


# --- office: the inbox

def new_requests(session: Session, company_id: UUID) -> list[BookingRequest]:
    """Requests waiting for the office, oldest first."""
    return list(session.scalars(
        select(BookingRequest)
        .where(BookingRequest.company_id == company_id,
               BookingRequest.status == BookingRequestStatus.NEW)
        .order_by(BookingRequest.created_at, BookingRequest.id)
    ))


def _request_for_update(session: Session, user: User, request_id: UUID) -> BookingRequest:
    # Locked, so two dispatchers clicking at once can't both turn it into a job.
    request = session.get(BookingRequest, request_id, with_for_update=True, populate_existing=True)
    if request is None or request.company_id != user.company_id:
        raise NotFound(f"Booking request {request_id}")
    return request


def accept(session: Session, user: User, request_id: UUID, *, customer_id: UUID | None = None) -> Job:
    """Turn a request into a Requested job for `customer_id`, or, with no id, for a new
    customer made from the contact details on the request. Nothing is matched automatically."""
    request = _request_for_update(session, user, request_id)
    if request.status != BookingRequestStatus.NEW:  # before creating anything
        raise DomainRuleViolation(f"This request was already {request.status.value}")

    if customer_id is None:
        customer = Customer(company_id=request.company_id, name=request.name, phone=request.phone,
                            email=request.email, address=request.address)
        session.add(customer)
        session.flush()  # no ORM relationships, so flush in FK order ourselves
    else:
        customer = CustomerRepository(session).get_for_company(customer_id, request.company_id)
        if customer is None:
            raise DomainRuleViolation("Unknown customer")

    details = [request.description, request.preferred_time and f"Preferred time: {request.preferred_time}"]
    job = Job(company_id=request.company_id, customer_id=customer.id, title=request.title,
              description="\n\n".join(d for d in details if d) or None)
    repo = JobRepository(session)
    repo.add(job)
    session.flush()  # the event's FK needs the job row first
    # The first line of the job's history says where it came from.
    repo.add_event(JobEvent(job_id=job.id, company_id=job.company_id, from_status=None,
                            to_status=JobStatus.REQUESTED, actor_user_id=user.id, note=BOOKED_ONLINE))
    request.accept(job, user)
    session.flush()
    return job


def decline(session: Session, user: User, request_id: UUID) -> BookingRequest:
    request = _request_for_update(session, user, request_id)
    request.decline(user)
    session.flush()
    return request
