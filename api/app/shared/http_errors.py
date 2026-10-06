"""Turn domain and service errors into HTTP responses, in one place."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth.service import EmailTaken, SignupClosed
from app.shared.errors import DomainRuleViolation, IllegalTransition
from app.spend.service import NotFound


def register(app: FastAPI) -> None:
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
