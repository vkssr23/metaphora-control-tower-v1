"""Fail-closed helpers for database-backed tenant isolation."""
import re
import uuid
from typing import Any, Mapping

from fastapi import HTTPException

MISSING_TENANT_MESSAGE = "Tenant membership is required"
TENANT_ID_PATTERN = re.compile(r"^ten_[0-9a-f]{32}$")


def validate_tenant_id(value: str) -> str:
    """Return a canonical tenant ID without normalizing caller input."""
    if not isinstance(value, str) or TENANT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("Tenant ID must use canonical format")
    return value


def new_tenant_id() -> str:
    return f"ten_{uuid.uuid4().hex}"


def require_tenant_id(current_user: Mapping[str, Any]) -> str:
    tenant_id = current_user.get("tenant_id")
    try:
        return validate_tenant_id(tenant_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=403, detail=MISSING_TENANT_MESSAGE)


def tenant_filter(current_user: Mapping[str, Any], additional_filter: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a fresh filter whose tenant cannot be overridden by its caller."""
    result = dict(additional_filter or {})
    result["tenant_id"] = require_tenant_id(current_user)
    return result


def tenant_document(current_user: Mapping[str, Any], document: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a fresh server-owned tenant document."""
    result = dict(document or {})
    result["tenant_id"] = require_tenant_id(current_user)
    return result


async def require_tenant_reference(collection: Any, current_user: Mapping[str, Any], record_id: str | None, operation: str) -> None:
    if record_id is None:
        return
    if not await collection.find_one(tenant_filter(current_user, {"id": record_id}), {"_id": 0}):
        raise HTTPException(status_code=404, detail="Not found")
