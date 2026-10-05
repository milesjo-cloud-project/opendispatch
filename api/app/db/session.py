"""Engine and session setup. Uses the same DATABASE_URL as the rest of the API."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.tables import start_mappers


def sqlalchemy_url(url: str | None = None) -> str:
    """DATABASE_URL is plain postgresql:// (psycopg reads it directly for health checks).
    SQLAlchemy would pick psycopg2 for that, so point it at psycopg 3 instead."""
    url = url or settings.database_url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def make_session_factory(url: str | None = None) -> sessionmaker:
    start_mappers()
    # Fail fast instead of hanging when the address is wrong or unreachable
    engine = create_engine(sqlalchemy_url(url), connect_args={"connect_timeout": 5})
    return sessionmaker(bind=engine, expire_on_commit=False)
