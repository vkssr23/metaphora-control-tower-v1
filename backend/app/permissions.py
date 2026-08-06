"""Central role-to-capability policy.

Admin shares normal owner capabilities; operations maps to dispatcher;
compliance maps to safety. Destructive seed remains separately owner-only.
"""
from typing import Any, Callable
from fastapi import Depends, HTTPException

ROLE_CAPABILITIES = {
    "owner": {"operational", "safety", "finance", "ai"},
    "admin": {"operational", "safety", "finance", "ai"},
    "dispatcher": {"operational"}, "operations": {"operational"},
    "safety": {"safety"}, "compliance": {"safety"},
    "finance": {"finance"}, "viewer": set(),
}


def require_capability(current_user: Callable[..., Any], capability: str):
    async def authorize(user: dict = Depends(current_user)) -> dict:
        if capability not in ROLE_CAPABILITIES.get(user.get("role", ""), set()):
            raise HTTPException(status_code=403, detail="Insufficient permission")
        return user
    return authorize


def require_owner(current_user: Callable[..., Any]):
    async def authorize(user: dict = Depends(current_user)) -> dict:
        if user.get("role") != "owner":
            raise HTTPException(status_code=403, detail="Owner permission required")
        return user
    return authorize
