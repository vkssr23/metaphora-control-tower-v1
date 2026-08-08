"""Minimum in-process worker core; no provider integrations or deployment wiring."""
from app.infrastructure.outbox import claim_next, mark_delivered, mark_failed


async def process_one(collection, *, tenant_id, worker_id, handlers, now=None):
    event = await claim_next(collection, tenant_id=tenant_id, worker_id=worker_id, now=now)
    if not event: return {"result": "idle"}
    handler = handlers.get(event["event_type"])
    if handler is None:
        ok, state = await mark_failed(collection, event, error_code="unknown_handler",
                                      safe_summary="No registered internal handler", retryable=False, now=now)
        return {"result": state if ok else "stale_claim", "event_id": event["id"]}
    try:
        await handler(event)
    except Exception:
        ok, state = await mark_failed(collection, event, error_code="handler_failure",
                                      safe_summary="Internal handler failed", retryable=True, now=now)
        return {"result": state if ok else "stale_claim", "event_id": event["id"]}
    ok = await mark_delivered(collection, event, now=now)
    return {"result": "delivered" if ok else "stale_claim", "event_id": event["id"]}
