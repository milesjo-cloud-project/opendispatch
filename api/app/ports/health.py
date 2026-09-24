from typing import Protocol


class DatabaseHealthPort(Protocol):
    def ping(self) -> bool: ...
