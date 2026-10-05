"""Sliding-window limits on public routes, kept in Postgres so they survive restarts and
hold across several API processes. The caller commits.

    if not rate_limit.allow(session, "booking", ip, limit=5, window=timedelta(hours=1)):
        ...answer 429
"""
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.tables import rate_limit_hits


def allow(session: Session, bucket: str, key: str, *, limit: int, window: timedelta,
          now: datetime | None = None) -> bool:
    """Count one hit for `key` and say whether it's within `limit` hits per `window`.
    A refused hit isn't counted, so someone who keeps trying is let back in once their
    earlier hits age out, not kept out for good."""
    now = now or datetime.now(timezone.utc)
    key_hash = hashlib.sha256(f"{bucket}:{key}".encode()).hexdigest()
    # One key at a time until commit, so two requests at once can't both squeeze in under the limit
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(key_hash))))
    # Old hits are never needed again; dropping them here keeps the table small
    session.execute(delete(rate_limit_hits).where(rate_limit_hits.c.bucket == bucket,
                                                  rate_limit_hits.c.created_at <= now - window))
    recent = session.scalar(
        select(func.count()).select_from(rate_limit_hits)
        .where(rate_limit_hits.c.bucket == bucket, rate_limit_hits.c.key_hash == key_hash)
    )
    if recent >= limit:
        return False
    session.execute(rate_limit_hits.insert().values(id=uuid4(), bucket=bucket, key_hash=key_hash,
                                                    created_at=now))
    return True
