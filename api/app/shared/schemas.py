"""Building blocks for every feature's request and response bodies (each feature has its own
schemas.py). Money is always integer cents; times are ISO 8601 with a zone."""
from pydantic import BaseModel, ConfigDict, Field


def Email(**kw):
    return Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", **kw)


def Password(**kw):
    # Checked against the policy in auth/domain.py; the cap here just stops huge bodies.
    return Field(min_length=1, max_length=1024, **kw)


def Cents(**kw):
    return Field(ge=0, le=100_000_000_00, **kw)  # up to $100M


def Text200(**kw):
    return Field(min_length=1, max_length=200, **kw)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
