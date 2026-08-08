"""Tenant-scoped durable operation registry and idempotency decisions."""
import re
import secrets
from datetime import datetime, timezone

from app.domain.operation_lifecycle import (
    ACTIVE_OPERATION_STATUSES, INVOICE_CREATE_STEPS, validate_step_transition,
    validate_steps, validate_transition,
)

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def utcnow(): return datetime.now(timezone.utc)
def iso(value=None): return (value or utcnow()).isoformat()


class OperationConflict(Exception):
    def __init__(self, code, operation): self.code, self.operation = code, operation


def idempotency_identity(tenant_id, operation_type, target_type, target_id, key):
    if key is not None and not IDEMPOTENCY_KEY.fullmatch(key): raise ValueError("Invalid Idempotency-Key")
    return {"tenant_id": tenant_id, "operation_type": operation_type, "target_type": target_type,
            "target_id": str(target_id)[:128], "idempotency_key": key}


async def create_or_replay(collection, *, tenant_id, operation_type, target_type, target_id,
                           idempotency_key, request_id, actor, audit_operation_id=None, stamp=None):
    identity = idempotency_identity(tenant_id, operation_type, target_type, target_id, idempotency_key)
    if idempotency_key:
        existing = await collection.find_one(identity, {"_id": 0})
        if existing:
            if existing.get("status") == "succeeded": return existing, True
            code = "operation_in_progress" if existing.get("status") in ACTIVE_OPERATION_STATUSES else existing.get("status", "operation_failed")
            raise OperationConflict(code, existing)
    stamp = iso(stamp); op_id = audit_operation_id or "op_" + secrets.token_hex(16)
    steps = [{"name": name, "status": "completed" if name == "operation_started" else "pending",
              "started_at": stamp if name == "operation_started" else None,
              "completed_at": stamp if name == "operation_started" else None, "failure_code": None}
             for name in INVOICE_CREATE_STEPS]
    validate_steps(operation_type, steps)
    doc = {"id": op_id, **identity, "request_id": str(request_id or "")[:128],
           "actor_user_id": str(actor.get("id", ""))[:128], "actor_role": str(actor.get("role", ""))[:64],
           "audit_operation_id": audit_operation_id or op_id, "execution_mode": "durable_saga", "status": "started",
           "created_at": stamp, "started_at": stamp, "completed_at": None, "failed_at": None,
           "updated_at": stamp, "version": 1, "current_step": "operation_started", "steps": steps,
           "result_reference": None, "failure_code": None, "failure_summary": None,
           "reconciliation_required": False}
    try:
        await collection.insert_one(doc)
    except Exception:
        if idempotency_key:
            winner = await collection.find_one(identity, {"_id": 0})
            if winner:
                if winner.get("status") == "succeeded": return winner, True
                code = "operation_in_progress" if winner.get("status") in ACTIVE_OPERATION_STATUSES else winner.get("status", "operation_failed")
                raise OperationConflict(code, winner)
        raise
    return doc, False


async def transition(collection, operation, *, status=None, step=None, step_status="completed",
                     failure_code=None, failure_summary=None, result_reference=None, stamp=None):
    stamp = iso(stamp); validate_steps(operation["operation_type"], operation["steps"])
    new_status = status or operation["status"]
    validate_transition(operation["status"], new_status)
    steps = [dict(x) for x in operation["steps"]]
    if step:
        validate_step_transition(steps, step, step_status)
        current = next((x for x in steps if x["name"] == step), None)
        current["status"] = step_status
        if step_status == "started": current["started_at"] = stamp
        if step_status in {"completed", "failed", "skipped"}: current["completed_at"] = stamp
        current["failure_code"] = str(failure_code)[:64] if failure_code else None
    update = {"status": new_status, "current_step": step or operation.get("current_step"), "steps": steps,
              "updated_at": stamp, "version": operation["version"] + 1,
              "failure_code": str(failure_code)[:64] if failure_code else operation.get("failure_code"),
              "failure_summary": str(failure_summary)[:256] if failure_summary else operation.get("failure_summary"),
              "reconciliation_required": new_status == "reconciliation_required"}
    if result_reference is not None: update["result_reference"] = result_reference
    if new_status == "succeeded": update["completed_at"] = stamp
    if new_status in {"failed", "partial", "reconciliation_required"}: update["failed_at"] = stamp
    result = await collection.update_one({"tenant_id": operation["tenant_id"], "id": operation["id"], "version": operation["version"]}, {"$set": update})
    if not result.matched_count: raise OperationConflict("operation_version_conflict", operation)
    operation.update(update)
    return operation
