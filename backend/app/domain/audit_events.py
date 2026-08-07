"""Construction, sanitization, integrity, and reconciliation for audit events."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from app.schemas.audit import AuditEntityType, AuditEvent, AuditOutcome, AuditPhase, AuditSource
from app.tenant import require_tenant_id

ALLOWED_ACTIONS = {
    "truck.created", "truck.updated", "truck.deleted",
    "driver.created", "driver.updated", "driver.deleted",
    "load.created", "load.updated", "load.deleted", "load.stage_changed",
    "load.exception_entered", "load.exception_recovered", "document.created",
    "invoice.created", "invoice.updated", "assumptions.updated",
    "alert.generated", "seed.executed", "tenant.signup_created",
    "load_passport.created", "load_passport.updated", "load_passport.checkpoint_updated",
    "load_passport.profitability_refreshed", "load_passport.submitted", "load_passport.approved",
    "load_passport.blocked", "load_passport.revoked", "load_passport.material_change_invalidated",
    "pickup_authorization.issued", "pickup_authorization.revoked",
    "execution_eligibility.created", "execution_eligibility.updated", "execution_eligibility.snapshots_refreshed",
    "execution_eligibility.evaluated", "execution_eligibility.submitted", "execution_eligibility.check_updated",
    "execution_eligibility.finding_resolved", "execution_eligibility.evidence_added", "execution_eligibility.hos_updated",
    "execution_eligibility.marked_eligible", "execution_eligibility.review_required", "execution_eligibility.blocked",
    "execution_eligibility.returned_to_review", "execution_eligibility.expired", "execution_eligibility.revoked",
    "execution_eligibility.material_change_invalidated", "execution_eligibility.passport_synchronized",
    "rate_confirmation.extraction_created", "rate_confirmation.extraction_updated",
    "rate_confirmation.compared", "rate_confirmation.submitted",
    "rate_confirmation.discrepancy_resolved", "rate_confirmation.accepted",
    "rate_confirmation.rejected", "rate_confirmation.returned_to_review",
    "rate_confirmation.superseded", "rate_confirmation.load_updated",
    "rate_confirmation.passport_synchronized",
    "rate_confirmation.extraction_confidence_updated",
    "party_verification.created", "party_verification.updated",
    "party_verification.snapshots_refreshed", "party_verification.evaluated",
    "party_verification.submitted", "party_verification.review_updated",
    "party_verification.finding_resolved", "party_verification.evidence_added",
    "party_verification.cleared", "party_verification.blocked",
    "party_verification.returned_to_review", "party_verification.expired",
    "party_verification.revoked", "party_verification.material_change_invalidated",
    "party_verification.passport_synchronized",
    "pickup_release.created", "pickup_release.updated", "pickup_release.snapshots_refreshed",
    "pickup_release.evaluated", "pickup_release.submitted", "pickup_release.checklist_updated",
    "pickup_release.finding_resolved", "pickup_release.evidence_added", "pickup_release.release_ready",
    "pickup_release.released", "pickup_release.authorization_issued", "pickup_release.authorization_revoked",
    "pickup_release.driver_acknowledged", "pickup_release.pickup_confirmed", "pickup_release.exception_opened",
    "pickup_release.blocked", "pickup_release.returned_to_review", "pickup_release.revoked",
    "pickup_release.material_change_invalidated", "pickup_release.custody_event_appended",
    "execution_session.started", "execution_session.progress_reported", "execution_session.paused",
    "execution_session.resumed", "execution_session.stop_arrived", "execution_session.stop_departed",
    "execution_session.detention_started", "execution_session.detention_ended", "execution_session.eta_evaluated",
    "execution_session.delivery_arrived", "execution_session.delivery_confirmed", "execution_session.completed",
    "execution_session.plan_amended", "execution_session.material_change_detected",
    "execution_exception.created", "execution_exception.acknowledged", "execution_exception.assigned",
    "execution_exception.escalated", "execution_exception.resolved", "execution_exception.waived",
    "invoice_readiness.created", "invoice_readiness.updated", "invoice_readiness.refreshed",
    "invoice_readiness.evaluated", "invoice_readiness.submitted_for_review",
    "invoice_readiness.finding_resolved", "invoice_readiness.evidence_added",
    "invoice_readiness.approved", "invoice_readiness.blocked", "invoice_readiness.reopened",
    "invoice_readiness.material_change_invalidated", "accessorial.created", "accessorial.updated",
    "accessorial.approved", "accessorial.rejected", "invoice_package.created",
    "invoice_package.superseded", "invoice.ready_for_submission",
}
SAFE_FIELDS = {
    "id", "truck_number", "status", "assigned_driver_id", "assigned_truck_id",
    "load_id", "stage", "exception_origin_stage", "driver_id", "truck_id",
    "bol_status", "pod_status", "invoice_status", "payment_status", "risk",
    "doc_type", "filename", "customer", "amount", "due_date", "paid_date",
    "dispute", "alert_type", "fuel_price", "mpg", "driver_pay_solo_cpm",
    "driver_pay_team_cpm", "insurance_per_week", "rental_per_week",
    "factoring_fee_pct", "default_toll", "target_margin_pct", "min_rpm",
    "min_net_profit", "count", "force",
    "passport_id", "version", "checkpoint_type", "reason_code", "pickup_authorization_id",
    "extraction_id", "document_id", "revision", "discrepancy_id", "discrepancy_type",
    "case_id", "review_domain", "finding_id", "risk_level", "signal_type", "release_case_id",
    "trailer_identifier", "custody_event_type", "changed_fields",
    "execution_state", "execution_health", "exception_id", "severity", "owner_role",
    "readiness_case_id", "package_id", "accessorial_id", "accessorial_type", "currency",
    "billable_total", "invoice_id", "verdict",
}
SENSITIVE = re.compile(r"password|secret|token|credential|authorization|api.?key|database|mongo|jwt|header|body|content", re.I)
MAX_FIELDS = 32
MAX_STRING = 256


def _safe_value(key: str, value: Any) -> Any:
    if isinstance(value, str):
        value = value[:MAX_STRING]
        if key == "url":
            parts = urlsplit(value)
            value = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_STRING]


def sanitize_summary(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Allowlist bounded operational metadata; never retain arbitrary payloads."""
    if not values:
        return {}
    result: dict[str, Any] = {}
    for key in sorted(values):
        if len(result) >= MAX_FIELDS:
            break
        if key in SAFE_FIELDS and not SENSITIVE.search(key):
            result[key] = _safe_value(key, values[key])
    return result


def canonical_event_json(event: Mapping[str, Any]) -> str:
    content = {key: value for key, value in event.items() if key not in {"_id", "integrity_hash"}}
    return json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def integrity_hash(event: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_event_json(event).encode("utf-8")).hexdigest()


def verify_integrity(event: Mapping[str, Any]) -> bool:
    claimed = event.get("integrity_hash")
    return isinstance(claimed, str) and claimed == integrity_hash(event)


def new_operation_id() -> str:
    return f"op_{uuid.uuid4().hex}"


def build_event(*, user: Mapping[str, Any], operation_id: str, phase: AuditPhase,
                action: str, entity_type: AuditEntityType, entity_id: str,
                source: AuditSource = AuditSource.API, correlation_id: str | None = None,
                changed_fields: list[str] | None = None,
                previous: Mapping[str, Any] | None = None, new: Mapping[str, Any] | None = None,
                reason_code: str = "", message: str = "") -> dict[str, Any]:
    if action not in ALLOWED_ACTIONS:
        raise ValueError("Unsupported audit action")
    outcomes = {AuditPhase.STARTED: AuditOutcome.PENDING, AuditPhase.SUCCEEDED: AuditOutcome.SUCCESS,
                AuditPhase.REJECTED: AuditOutcome.REJECTED, AuditPhase.FAILED: AuditOutcome.FAILURE}
    event = {
        "id": f"aud_{uuid.uuid4().hex}", "operation_id": operation_id,
        "tenant_id": require_tenant_id(user), "occurred_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1, "phase": phase.value, "outcome": outcomes[phase].value,
        "action": action, "entity_type": entity_type.value, "entity_id": str(entity_id)[:128],
        "actor_id": str(user.get("id", ""))[:128],
        "actor_email": str(user.get("email", "")).strip().lower()[:MAX_STRING],
        "actor_role": str(user.get("role", ""))[:64], "source": source.value,
        "correlation_id": (correlation_id or operation_id)[:128],
        "changed_fields": sorted({k for k in (changed_fields or []) if k in SAFE_FIELDS})[:MAX_FIELDS],
        "previous_state_summary": sanitize_summary(previous), "new_state_summary": sanitize_summary(new),
        "reason_code": str(reason_code)[:64], "message": str(message)[:MAX_STRING],
    }
    event["integrity_hash"] = integrity_hash(event)
    return AuditEvent.model_validate(event).model_dump(mode="json")


async def incomplete_operations(collection: Any, tenant_id: str, older_than_seconds: int = 300,
                                limit: int = 100) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(60, older_than_seconds))).isoformat()
    events = await collection.find({"tenant_id": tenant_id}, {"_id": 0}).sort("occurred_at", -1).to_list(1000)
    terminal = {e["operation_id"] for e in events if e.get("phase") in {"succeeded", "rejected", "failed"}}
    return [e for e in events if e.get("phase") == "started" and e.get("occurred_at", "") < cutoff
            and e.get("operation_id") not in terminal][:max(1, min(limit, 100))]
