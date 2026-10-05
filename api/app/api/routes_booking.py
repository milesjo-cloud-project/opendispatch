"""Online booking: the owner's link, the public form behind /book/<booking_id>, and the office inbox.

The two /public routes need no login, so they say as little as possible: a wrong id and
booking turned off both answer 404, and a booking answers with no ids. Sending is limited
per IP address (settings.booking_limit_per_hour) and has a honeypot field for bots.
"""
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import Actor, client_ip, get_session, office_actor, owner_actor
from app.api.schemas import (
    BookingAcceptIn,
    BookingIn,
    BookingLinkOut,
    BookingPageOut,
    BookingReceivedOut,
    BookingRequestOut,
    JobOut,
)
from app.config import settings
from app.domain.entities import Company, Customer
from app.services import booking, rate_limit

router = APIRouter(tags=["online booking"])
BOOKING_WINDOW = timedelta(hours=1)


# --- owner

@router.post("/company/booking-link", response_model=BookingLinkOut, status_code=201)
def turn_on_booking(actor: Actor = Depends(owner_actor), session: Session = Depends(get_session)):
    """Owner only. Turn online booking on, or replace the link (the old one stops working)."""
    booking_id = booking.turn_on(session.get(Company, actor.user.company_id))
    session.commit()
    return BookingLinkOut(booking_id=booking_id, path=f"/book/{booking_id}")


@router.delete("/company/booking-link", status_code=204)
def turn_off_booking(actor: Actor = Depends(owner_actor), session: Session = Depends(get_session)):
    """Owner only. Turn online booking off. Requests already sent stay in the inbox."""
    booking.turn_off(session.get(Company, actor.user.company_id))
    session.commit()
    return Response(status_code=204)


# --- public: no login

@router.get("/public/book/{booking_id}", response_model=BookingPageOut)
def booking_page(booking_id: str, session: Session = Depends(get_session)):
    return BookingPageOut(company_name=booking.company_for_booking_id(session, booking_id).name)


@router.post("/public/book/{booking_id}", response_model=BookingReceivedOut, status_code=201)
def book(booking_id: str, body: BookingIn, request: Request, session: Session = Depends(get_session)):
    # Counted before anything else, so tries with wrong links count too (no guessing ids)
    if not rate_limit.allow(session, "booking", client_ip(request),
                            limit=settings.booking_limit_per_hour, window=BOOKING_WINDOW):
        session.commit()  # keep the cleanup of old hits
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Too many booking requests from your network. Please try again later.",
                            headers={"Retry-After": str(int(BOOKING_WINDOW.total_seconds()))})
    session.commit()  # the hit stays counted even if what follows is refused
    company = booking.company_for_booking_id(session, booking_id)
    if body.website:
        # A bot. It gets the same answer as a person, so it can't tell it was caught.
        return BookingReceivedOut(company_name=company.name)
    booking.submit(session, booking_id, **body.model_dump(exclude={"website"}))
    session.commit()
    return BookingReceivedOut(company_name=company.name)


# --- office

@router.get("/booking-requests", response_model=list[BookingRequestOut])
def list_booking_requests(actor: Actor = Depends(office_actor), session: Session = Depends(get_session)):
    """Office only. Requests waiting for a decision, oldest first."""
    return booking.new_requests(session, actor.user.company_id)


@router.post("/booking-requests/{request_id}/accept", response_model=JobOut)
def accept_booking_request(request_id: UUID, body: BookingAcceptIn, actor: Actor = Depends(office_actor),
                           session: Session = Depends(get_session)):
    """Office only. Make a Requested job for `customer_id`, or for a new customer made from
    the request. Schedule it afterwards like any other job."""
    job = booking.accept(session, actor.user, request_id, customer_id=body.customer_id)
    session.commit()
    customer = session.get(Customer, job.customer_id)
    return JobOut.model_validate(job).model_copy(
        update={"customer_name": customer.name, "customer_phone": customer.phone})


@router.post("/booking-requests/{request_id}/decline", response_model=BookingRequestOut)
def decline_booking_request(request_id: UUID, actor: Actor = Depends(office_actor),
                            session: Session = Depends(get_session)):
    """Office only."""
    request = booking.decline(session, actor.user, request_id)
    session.commit()
    return request
