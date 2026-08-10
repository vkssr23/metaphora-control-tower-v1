"""Pure rules for stored freight-document evidence.

Storage proves byte presence and identity only.  It does not prove origin,
authenticity, extraction, acceptance, or party verification.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import PurePath, PureWindowsPath


MAX_FILENAME_LENGTH = 180
DEFAULT_MAX_UPLOAD_BYTES = 15 * 1024 * 1024
SUPPORTED_CONTENT_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png"})


class DocumentValidationError(ValueError):
    pass


def safe_original_filename(value: str | None) -> str:
    raw = (value or "document").replace("\\", "/")
    name = PurePath(raw).name
    # PurePath on POSIX does not understand drive-letter paths after replacement.
    name = PureWindowsPath(name).name
    name = "".join("_" if ord(char) < 32 or ord(char) == 127 else char for char in name)
    name = re.sub(r"\s+", " ", name).strip(" .") or "document"
    if len(name) > MAX_FILENAME_LENGTH:
        suffix = PurePath(name).suffix[:16]
        name = name[: MAX_FILENAME_LENGTH - len(suffix)].rstrip(" .") + suffix
    return name


def validate_content(content_type: str | None, content: bytes) -> str:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime not in SUPPORTED_CONTENT_TYPES:
        raise DocumentValidationError("Unsupported document content type")
    valid = {
        "application/pdf": content.startswith(b"%PDF-"),
        "image/jpeg": len(content) >= 4 and content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
    }[mime]
    if not valid:
        raise DocumentValidationError("Document bytes do not match the declared content type")
    return mime


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

