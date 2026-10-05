"""Login rules: password policy, lockout after repeated failures, and login sessions.

Hashing passwords and generating tokens happen in adapters/services; this module only
holds the rules, so they're testable without argon2 or a database.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.shared.errors import DomainRuleViolation

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128  # hashing very long inputs is a cheap way to burn server CPU

MAX_FAILED_LOGINS = 10
LOCKOUT = timedelta(minutes=15)

SESSION_LIFETIME = timedelta(days=14)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def check_password_policy(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise DomainRuleViolation(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise DomainRuleViolation(f"Password must be at most {MAX_PASSWORD_LENGTH} characters")
    if not password.strip():
        raise DomainRuleViolation("Password can't be only spaces")


def normalize_phone(raw: str) -> str:
    """Return the number in E.164 form (+15551234567), which is what SMS providers need.

    Accepts common US formats: a bare 10-digit number is assumed to be US (+1).
    Anything else must already start with + and a country code.
    """
    digits = re.sub(r"[\s\-().]", "", raw)
    if re.fullmatch(r"\d{10}", digits):
        digits = "+1" + digits
    elif re.fullmatch(r"1\d{10}", digits):
        digits = "+" + digits
    if not re.fullmatch(r"\+[1-9]\d{7,14}", digits):
        raise DomainRuleViolation(f"'{raw}' isn't a phone number we can text")
    return digits


@dataclass(eq=False)
class AuthSession:
    """One logged-in device. The token itself is never stored, only its hash."""
    user_id: UUID
    company_id: UUID
    token_hash: str
    expires_at: datetime | None = None  # defaults to created_at + SESSION_LIFETIME
    revoked_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.expires_at is None:
            self.expires_at = self.created_at + SESSION_LIFETIME

    def is_active(self, now: datetime | None = None) -> bool:
        now = now or _now()
        return self.revoked_at is None and now < self.expires_at

    def revoke(self) -> None:
        if self.revoked_at is None:
            self.revoked_at = _now()


RESET_LIFETIME = timedelta(hours=1)
MAX_RESETS_PER_HOUR = 5


@dataclass(eq=False)
class PasswordResetToken:
    """A one-time link to set a new password. Like login tokens, only the hash is stored."""
    user_id: UUID
    company_id: UUID
    token_hash: str
    expires_at: datetime | None = None  # defaults to created_at + RESET_LIFETIME
    used_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.expires_at is None:
            self.expires_at = self.created_at + RESET_LIFETIME

    def is_usable(self, now: datetime | None = None) -> bool:
        now = now or _now()
        return self.used_at is None and now < self.expires_at

    def use(self, now: datetime | None = None) -> None:
        now = now or _now()
        if not self.is_usable(now):
            raise DomainRuleViolation("This reset link is invalid or has expired")
        self.used_at = now
