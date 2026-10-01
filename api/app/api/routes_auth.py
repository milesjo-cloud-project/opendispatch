"""Sign up, log in, log out, and the logged-in user's own account."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import Actor, current_actor, get_hasher, get_session, technician_for
from app.api.schemas import LoginIn, MeOut, MeUpdate, PasswordChangeIn, SignupIn, TokenOut
from app.ports.passwords import PasswordHasherPort
from app.services import auth

router = APIRouter(tags=["auth"])


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
