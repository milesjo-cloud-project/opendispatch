"""Port: sending an email. Adapters: SMTP (any provider), the log, and a fake for tests."""

from typing import Protocol


class EmailPort(Protocol):
    def send(self, to: str, subject: str, body: str) -> None:
        """Send a plain-text email. Raise if the server refused it."""
        ...
