"""Sign up, log in, log out, and the logged-in user's own account."""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth import service as auth
from app.auth.schemas import (
    LoginIn,
    MeOut,
    MeUpdate,
    PasswordChangeIn,
    ResetConfirmIn,
    ResetRequestIn,
    SignupIn,
    TokenOut,
)
from app.config import settings
from app.shared.deps import Actor, current_actor, get_email, get_hasher, get_session, technician_for
from app.shared.ports import EmailPort, PasswordHasherPort

router = APIRouter(tags=["auth"])
log = logging.getLogger("opendispatch.auth")


def me_out(user, technician) -> MeOut:
    return MeOut(id=user.id, company_id=user.company_id, email=user.email, role=user.role,
                 phone=user.phone, technician_id=technician.id if technician else None)


def token_out(result: auth.LoginResult, technician=None) -> TokenOut:
    return TokenOut(token=result.token, expires_at=result.auth_session.expires_at,
                    user=me_out(result.user, technician))


@router.post("/auth/signup", response_model=TokenOut, status_code=201)
def signup(body: SignupIn, session: Session = Depends(get_session),
           hasher: PasswordHasherPort = Depends(get_hasher)):
    """Create a company and its owner account, and log in."""
    result = auth.signup(session, hasher, company_name=body.company_name, email=body.email,
                         password=body.password, phone=body.phone)
    session.commit()
    return token_out(result)


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, session: Session = Depends(get_session),
          hasher: PasswordHasherPort = Depends(get_hasher)):
    try:
        result = auth.login(session, hasher, email=body.email, password=body.password)
    except auth.InvalidCredentials:
        session.commit()  # keep the failed-attempt count
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password") from None
    session.commit()
    return token_out(result, technician_for(session, result.user))


def _send_quietly(email: EmailPort, to: str, subject: str, body: str) -> None:
    # Runs after the response; a mail server hiccup must not surface as an error to anyone.
    try:
        email.send(to, subject, body)
    except Exception:
        log.exception("Password reset email failed to send")


@router.post("/auth/password-reset/request", status_code=202)
def request_password_reset(body: ResetRequestIn, background: BackgroundTasks,
                           session: Session = Depends(get_session),
                           email: EmailPort = Depends(get_email)):
    """Email a one-hour reset link. Answers the same whether or not the account exists."""
    request = auth.request_password_reset(session, email=body.email)
    session.commit()
    if request is not None:
        # After '#', so the token never reaches a server log or a Referer header
        link = f"{settings.app_base_url.rstrip('/')}/reset-password#token={request.token}"
        subject, text = auth.reset_email(link)
        background.add_task(_send_quietly, email, request.user.email, subject, text)
    return {"detail": "If that email has an account, a reset link is on its way."}


@router.post("/auth/password-reset/confirm", status_code=204)
def confirm_password_reset(body: ResetConfirmIn, session: Session = Depends(get_session),
                           hasher: PasswordHasherPort = Depends(get_hasher)):
    """Set a new password from a reset link. Logs the account out everywhere."""
    try:
        auth.confirm_password_reset(session, hasher, token=body.token, new_password=body.new_password)
    except auth.InvalidResetToken:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired") from None
    session.commit()
    return Response(status_code=204)


@router.post("/auth/logout", status_code=204)
def logout(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    auth.logout(actor.auth_session)
    session.commit()
    return Response(status_code=204)


@router.get("/me", response_model=MeOut)
def me(actor: Actor = Depends(current_actor)):
    return me_out(actor.user, actor.technician)


@router.patch("/me", response_model=MeOut)
def update_me(body: MeUpdate, actor: Actor = Depends(current_actor),
              session: Session = Depends(get_session)):
    """Set or clear your phone number (where SMS alerts go)."""
    actor.user.set_phone(body.phone)
    session.commit()
    return me_out(actor.user, actor.technician)


@router.post("/me/password", status_code=204)
def change_password(body: PasswordChangeIn, actor: Actor = Depends(current_actor),
                    session: Session = Depends(get_session),
                    hasher: PasswordHasherPort = Depends(get_hasher)):
    """Change your password. Logs out your other devices."""
    try:
        auth.change_password(session, hasher, user=actor.user, current_password=body.current_password,
                             new_password=body.new_password, keep=actor.auth_session)
    except auth.InvalidCredentials:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is wrong") from None
    session.commit()
    return Response(status_code=204)
