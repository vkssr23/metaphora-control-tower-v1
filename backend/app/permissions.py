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


def require_audit_reader(current_user: Callable[..., Any]):
    async def authorize(user: dict = Depends(current_user)) -> dict:
        if user.get("role") not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="Audit reader permission required")
        return user
    return authorize

ACTION_OWNER_CAPABILITY={"operations":"operational","safety":"safety","finance":"finance","admin":"admin"}
ACTION_CATEGORY_OWNER={"execution":"operations","safety":"safety","fraud_risk":"safety","documents":"operations","finance":"finance","reconciliation":"admin","platform_integrity":"admin"}

def can_acknowledge_action(user: dict, action: dict) -> bool:
    role=user.get("role","")
    if role in {"owner","admin"}:return True
    owner=action.get("owner_role");category=action.get("category")
    if ACTION_CATEGORY_OWNER.get(category)!=owner:return False
    capability=ACTION_OWNER_CAPABILITY.get(owner)
    return bool(capability and capability in ROLE_CAPABILITIES.get(role,set()))

def enforce_action_acknowledgement(user: dict, action: dict) -> None:
    if not can_acknowledge_action(user,action):
        raise HTTPException(status_code=403,detail="Insufficient permission for this action")
