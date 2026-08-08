"""Idempotent durable reconciliation evidence."""
import secrets
from datetime import datetime, timezone

ALLOWED_REASONS = frozenset({"package_failure", "invoice_failure", "readiness_finalize_race", "outbox_failure", "outbox_dead_letter", "operation_finalization_failed_after_outbox"})


async def ensure_reconciliation(collection, *, tenant_id, operation_id, domain, entity_type, entity_id,
                                reason_code, summary, owner_role="finance", severity="high", stamp=None):
    if reason_code not in ALLOWED_REASONS: raise ValueError("Unsupported reconciliation reason")
    identity = {"tenant_id": tenant_id, "operation_id": operation_id, "reason_code": reason_code,
                "entity_type": entity_type, "entity_id": str(entity_id)[:128]}
    existing = await collection.find_one(identity, {"_id": 0})
    if existing: return existing
    now = (stamp or datetime.now(timezone.utc)).isoformat()
    doc = {"id": "rec_" + secrets.token_hex(16), **identity, "domain": domain, "severity": severity,
           "status": "open", "owner_role": owner_role, "summary": str(summary)[:256],
           "created_at": now, "updated_at": now, "resolved_at": None, "version": 1,
           "resolution_code": None, "resolution_summary": None}
    try: await collection.insert_one(doc)
    except Exception:
        winner = await collection.find_one(identity, {"_id": 0})
        if winner: return winner
        raise
    return doc
