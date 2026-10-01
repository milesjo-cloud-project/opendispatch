"""Turn domain and service errors into HTTP responses, in one place."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import DomainRuleViolation, IllegalTransition
from app.services.auth import EmailTaken
from app.services.spend import NotFound


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
