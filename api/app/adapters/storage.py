"""Persistent local storage for job documents, suitable for self-hosted installs."""
from pathlib import Path


class FileSystemStorage:
    def __init__(self, directory: str):
        self.directory = Path(directory).expanduser().resolve()

    def save(self, key: str, content: bytes) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / key).write_bytes(content)

    def path(self, key: str) -> Path:
        # Keys are generated UUID hex strings, but keep the boundary explicit.
        if not key.isalnum():
            raise ValueError("Invalid storage key")
        return self.directory / key
