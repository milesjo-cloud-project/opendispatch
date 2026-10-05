from fastapi import Depends, FastAPI, Response

from app.auth import routes as auth_routes
from app.booking import routes as booking_routes
from app.company import routes as company_routes
from app.config import settings
from app.db.health import PostgresHealth
from app.jobs import routes as job_routes
from app.jobs import tracking as tracking_routes
from app.shared import http_errors
from app.shared.ports import DatabaseHealthPort

# Interactive docs only locally; in dev/prod they'd advertise every endpoint to anyone.
app = FastAPI(
    title="OpenDispatch API",
    docs_url="/docs" if settings.is_local else None,
    redoc_url="/redoc" if settings.is_local else None,
    openapi_url="/openapi.json" if settings.is_local else None,
)
http_errors.register(app)
app.include_router(auth_routes.router)
app.include_router(company_routes.router)
app.include_router(job_routes.router)
app.include_router(tracking_routes.router)
app.include_router(booking_routes.router)


def get_db_health() -> DatabaseHealthPort:
    return PostgresHealth(settings.database_url)


@app.get("/healthz")
def healthz() -> dict:
    """Liveness: the process is up. Never touches the database."""
    return {"status": "ok", "env": settings.app_env}


@app.get("/readyz")
def readyz(response: Response, db: DatabaseHealthPort = Depends(get_db_health)) -> dict:
    """Readiness: the API can reach Postgres."""
    if db.ping():
        return {"status": "ready", "database": "up"}
    response.status_code = 503
    return {"status": "not_ready", "database": "down"}
