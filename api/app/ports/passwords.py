"""Port: turning passwords into hashes and checking them. Adapter: argon2."""

from typing import Protocol


class PasswordHasherPort(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool:
        """True when the hash was made with older settings and should be redone at next login."""
        ...
