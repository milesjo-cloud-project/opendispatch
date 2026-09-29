"""In-memory SMS for tests."""


class FakeSms:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    def send(self, to: str, body: str) -> None:
        if self.fail:
            raise ConnectionError("sms provider is down")
        self.sent.append((to, body))
