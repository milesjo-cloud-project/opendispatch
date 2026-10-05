from fastapi import Depends, FastAPI, Response

from app.adapters.db.postgres import PostgresHealth
from app.api import errors, routes_admin, routes_auth, routes_booking, routes_jobs, routes_tracking
from app.config import settings
from app.ports.health import DatabaseHealthPort

# Interactive docs only locally; in dev/prod they'd advertise every endpoint to anyone.
app = FastAPI(
    title="OpenDispatch API",
    docs_url="/docs" if settings.is_local else None,
    redoc_url="/redoc" if settings.is_local else None,
    openapi_url="/openapi.json" if settings.is_local else None,
)
errors.register(app)
app.include_router(routes_auth.router)
app.include_router(routes_admin.router)
app.include_router(routes_jobs.router)
app.include_router(routes_tracking.router)
app.include_router(routes_booking.router)


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
