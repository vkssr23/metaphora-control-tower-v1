"""Controlled outbox vocabulary and deterministic retry policy."""
from datetime import timedelta

EVENT_PAYLOAD_FIELDS = {
    "invoice.ready_for_submission": frozenset({"invoice_id", "package_id", "readiness_case_id", "load_id"}),
    "invoice.reconciliation_required": frozenset({"invoice_id", "readiness_case_id", "reason_code"}),
    "operation.reconciliation_required": frozenset({"entity_id", "reason_code"}),
}
MAX_ATTEMPTS = 5


def validate_payload(event_type: str, payload: dict) -> dict:
    allowed = EVENT_PAYLOAD_FIELDS.get(event_type)
    if allowed is None or not isinstance(payload, dict) or set(payload) - allowed or len(payload) > 8:
        raise ValueError("Unsupported or unsafe outbox payload")
    clean = {}
    for key, value in payload.items():
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError("Outbox payload values must be scalar")
        clean[key] = value[:128] if isinstance(value, str) else value
    return clean


def retry_delay(attempt_count: int) -> timedelta:
    return timedelta(seconds=min(3600, 30 * (2 ** max(0, attempt_count - 1))))

