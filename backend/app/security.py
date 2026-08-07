"""JWT validation and database-backed authenticated-user dependency."""
from datetime import datetime, timezone
from typing import Any, Optional

import jwt
from fastapi import Header, HTTPException


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    """Serialize only fields that are part of the public user contract."""
    allowed = ("id", "email", "name", "role", "tenant_id", "active", "is_active", "created_at")
    return {key: user[key] for key in allowed if key in user}


def user_is_active(user: dict[str, Any]) -> bool:
    status = str(user.get("status", "active")).strip().lower()
    return not (user.get("disabled") is True or user.get("active") is False
                or status in {"disabled", "inactive", "deleted"}
                or user.get("deleted_at") is not None)


def create_token(user: dict[str, Any], secret: str) -> str:
    payload = {
        "id": user["id"], "email": user["email"], "role": user["role"], "name": user["name"],
        "exp": datetime.now(timezone.utc).timestamp() + 30 * 24 * 60 * 60,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def authenticated_user_dependency(db: Any, secret: str):
    async def get_current_user(authorization: Optional[str] = Header(None)) -> dict[str, Any]:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid authentication")
        token = authorization[7:].strip()
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            raise HTTPException(status_code=401, detail="Missing or invalid authentication")
        user_id = payload.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Missing or invalid authentication")
        user = await db.users.find_one({"id": user_id})
        if not user or not user_is_active(user):
            raise HTTPException(status_code=401, detail="User is unavailable")
        normalized = public_user(user)
        # public_user receives only the freshly loaded database record. Tenant
        # membership in this response is informational, never JWT authority.
        normalized["email"] = str(normalized.get("email", "")).strip().lower()
        normalized["role"] = str(normalized.get("role", "viewer")).strip().lower()
        return normalized
    return get_current_user
