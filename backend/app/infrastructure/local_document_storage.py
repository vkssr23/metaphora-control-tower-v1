"""Private local-filesystem adapter for development and controlled tests."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

from .document_storage import DocumentObjectMissing, DocumentStorageError


class LocalDocumentStorage:
    provider = "local_filesystem"

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, storage_key: str) -> Path:
        if not storage_key or len(storage_key) > 240 or "\\" in storage_key:
            raise DocumentStorageError("Invalid storage key")
        candidate = (self.root / storage_key).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise DocumentStorageError("Invalid storage key") from exc
        return candidate

    def put(self, storage_key: str, content: bytes) -> None:
        target = self._path(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise DocumentStorageError("Document object already exists")
        fd, temporary = tempfile.mkstemp(prefix=".upload-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            # Same-directory hard-link publication is atomic and refuses an
            # existing target, preserving immutable-object semantics.
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise DocumentStorageError("Document object already exists") from exc
            os.unlink(temporary)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def open(self, storage_key: str):
        try:
            return self._path(storage_key).open("rb")
        except FileNotFoundError as exc:
            raise DocumentObjectMissing("Stored document object is missing") from exc

    def exists(self, storage_key: str) -> bool:
        return self._path(storage_key).is_file()

    def delete_if_uncommitted(self, storage_key: str) -> None:
        try:
            self._path(storage_key).unlink()
        except FileNotFoundError:
            return
