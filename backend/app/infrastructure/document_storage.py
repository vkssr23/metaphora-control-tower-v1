"""Narrow storage boundary for immutable document objects."""
from __future__ import annotations

from typing import BinaryIO, Protocol


class DocumentStorageError(RuntimeError):
    pass


class DocumentObjectMissing(DocumentStorageError):
    pass


class DocumentStorage(Protocol):
    provider: str

    def put(self, storage_key: str, content: bytes) -> None: ...
    def open(self, storage_key: str) -> BinaryIO: ...
    def exists(self, storage_key: str) -> bool: ...
    def delete_if_uncommitted(self, storage_key: str) -> None: ...

