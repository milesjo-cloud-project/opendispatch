"""Port: sending a text message. Adapters: Twilio, and a fake for tests."""

from typing import Protocol


class SmsPort(Protocol):
    def send(self, to: str, body: str) -> None:
        """Send `body` to an E.164 number. Raise if the provider refused it."""
        ...
