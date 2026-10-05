"""argon2id, the current OWASP recommendation, with argon2-cffi's default cost settings."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2Hasher:
    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._ph = hasher or PasswordHasher()

    def hash(self, password: str) -> str:
        return self._ph.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._ph.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        return self._ph.check_needs_rehash(password_hash)
