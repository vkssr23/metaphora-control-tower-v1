"""Narrow runtime wiring shared by extracted API modules."""
from datetime import datetime, timezone
from fastapi import HTTPException
import logging
import uuid

_db_getter = None
_settings_getter = None

class _Proxy:
    def __init__(self, getter_name):
        object.__setattr__(self, "_getter_name", getter_name)
    def _target(self):
        getter = _db_getter if self._getter_name == "db" else _settings_getter
        if getter is None:
            raise RuntimeError(f"{self._getter_name} runtime is not configured")
        return getter()
    def __getattr__(self, name):
        return getattr(self._target(), name)

db = _Proxy("db")
settings = _Proxy("settings")

def configure_runtime(db_getter, settings_getter):
    global _db_getter, _settings_getter
    _db_getter = db_getter
    _settings_getter = settings_getter

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def new_id(prefix=""):
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"

def clean_doc(document):
    if document and "_id" in document:
        document.pop("_id", None)
    return document

async def safe_db(awaitable, operation):
    try:
        return await awaitable
    except HTTPException:
        raise
    except Exception:
        logging.error("Database operation failed during %s", operation)
        raise HTTPException(500, "Database operation failed")

async def audited_db(audit, awaitable, operation):
    try:
        return await safe_db(awaitable, operation)
    except HTTPException as exc:
        if exc.status_code < 500:
            await audit.rejected("operation_rejected")
        else:
            await audit.failed("internal_failure")
        raise
