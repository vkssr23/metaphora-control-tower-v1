"""Durable at-least-once outbox primitives with guarded lease ownership."""
import secrets
from datetime import datetime, timedelta, timezone

from app.domain.outbox_policy import MAX_ATTEMPTS, retry_delay, validate_payload

def utcnow(): return datetime.now(timezone.utc)
def iso(value): return value.isoformat()


async def enqueue(collection, *, tenant_id, operation_id, event_type, aggregate_type, aggregate_id, payload, stamp=None):
    existing = await collection.find_one({"tenant_id": tenant_id, "operation_id": operation_id, "event_type": event_type,
                                          "aggregate_type": aggregate_type, "aggregate_id": aggregate_id}, {"_id": 0})
    if existing: return existing
    now = stamp or utcnow(); doc = {"id": "out_" + secrets.token_hex(16), "tenant_id": tenant_id,
        "operation_id": operation_id, "event_type": event_type, "aggregate_type": aggregate_type,
        "aggregate_id": str(aggregate_id)[:128], "payload_version": 1, "payload": validate_payload(event_type, payload),
        "created_at": iso(now), "available_at": iso(now), "status": "pending", "attempt_count": 0,
        "last_attempt_at": None, "next_attempt_at": iso(now), "claim_owner": None, "claim_token": None,
        "claim_expires_at": None, "delivered_at": None, "dead_lettered_at": None,
        "last_error_code": None, "last_error_summary": None, "version": 1}
    try: await collection.insert_one(doc)
    except Exception:
        winner = await collection.find_one({"tenant_id": tenant_id, "operation_id": operation_id, "event_type": event_type,
                                            "aggregate_type": aggregate_type, "aggregate_id": aggregate_id}, {"_id": 0})
        if winner: return winner
        raise
    return doc


async def claim_next(collection, *, tenant_id, worker_id, now=None, lease_seconds=60):
    now = now or utcnow(); now_s = iso(now)
    candidates = await collection.find({"tenant_id": tenant_id}, {"_id": 0}).sort([("available_at", 1), ("id", 1)]).to_list(100)
    for event in candidates:
        reclaim = event.get("status") == "processing" and event.get("claim_expires_at") and event["claim_expires_at"] <= now_s
        ready = event.get("status") in {"pending", "retryable"} and (event.get("next_attempt_at") or event["available_at"]) <= now_s
        if not (ready or reclaim): continue
        token = secrets.token_hex(16); version = event["version"]
        result = await collection.update_one({"tenant_id": tenant_id, "id": event["id"], "version": version,
                                              "status": event["status"], "claim_token": event.get("claim_token")},
            {"$set": {"status": "processing", "claim_owner": str(worker_id)[:128], "claim_token": token,
                      "claim_expires_at": iso(now + timedelta(seconds=max(5, min(3600, lease_seconds)))),
                      "attempt_count": event.get("attempt_count", 0) + 1, "last_attempt_at": now_s,
                      "version": version + 1}})
        if result.matched_count:
            claimed = await collection.find_one({"tenant_id": tenant_id, "id": event["id"]}, {"_id": 0})
            return claimed
    return None


async def mark_delivered(collection, event, *, now=None):
    now = now or utcnow(); result = await collection.update_one(
        {"tenant_id": event["tenant_id"], "id": event["id"], "status": "processing",
         "version": event["version"], "claim_owner": event["claim_owner"], "claim_token": event["claim_token"]},
        {"$set": {"status": "delivered", "delivered_at": iso(now), "claim_owner": None, "claim_token": None,
                  "claim_expires_at": None, "version": event["version"] + 1}})
    return bool(result.matched_count)


async def mark_failed(collection, event, *, error_code, safe_summary, retryable=True, now=None):
    now = now or utcnow(); exhausted = event["attempt_count"] >= MAX_ATTEMPTS
    status = "retryable" if retryable and not exhausted else "dead_letter"
    update = {"status": status, "claim_owner": None, "claim_token": None, "claim_expires_at": None,
              "last_error_code": str(error_code)[:64], "last_error_summary": str(safe_summary)[:256],
              "version": event["version"] + 1}
    if status == "retryable": update["next_attempt_at"] = iso(now + retry_delay(event["attempt_count"]))
    else: update["dead_lettered_at"] = iso(now)
    result = await collection.update_one({"tenant_id": event["tenant_id"], "id": event["id"], "status": "processing",
                                          "version": event["version"], "claim_owner": event["claim_owner"],
                                          "claim_token": event["claim_token"]}, {"$set": update})
    return bool(result.matched_count), status
