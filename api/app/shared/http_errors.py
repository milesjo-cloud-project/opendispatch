"""Turn domain and service errors into HTTP responses, in one place."""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError

from app.auth.service import EmailTaken, SignupClosed
from app.shared.errors import DomainRuleViolation, IllegalTransition
from app.spend.service import NotFound

log = logging.getLogger("opendispatch.http")


def register(app: FastAPI) -> None:
    @app.exception_handler(DataError)
    def _bad_data(_: Request, exc: DataError):
        """Input Postgres refuses to store, which is the caller's fault, not a server fault.

        A NUL byte anywhere in a string is the one that turns up in practice: Postgres
        rejects it in any text column, so `?booking_id=%00`, a booking form with one in
        the name, or a login with one in the email each used to answer 500 from a public
        endpoint. Anything of this shape is a 400, and the detail stays generic because
        the exception text names tables and columns.
        """
        log.warning("Rejected a request Postgres wouldn't store: %s", type(exc).__name__)
        return JSONResponse({"detail": "Your request contained characters we can't accept"},
                            status_code=400)
    @app.exception_handler(IllegalTransition)
    def _illegal(_: Request, exc: IllegalTransition):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(DomainRuleViolation)
    def _rule(_: Request, exc: DomainRuleViolation):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(NotFound)
    def _not_found(_: Request, exc: NotFound):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    @app.exception_handler(EmailTaken)
    def _taken(_: Request, exc: EmailTaken):
        return JSONResponse({"detail": "An account with that email already exists"}, status_code=409)

    @app.exception_handler(SignupClosed)
    def _signup_closed(_: Request, exc: SignupClosed):
        return JSONResponse({"detail": "This server isn't taking new sign-ups. "
                                       "Ask your company's owner to add you."}, status_code=403)
