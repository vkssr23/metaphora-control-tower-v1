"""Authoritative, declarative Mongo index manifest (never auto-applied)."""
from dataclasses import dataclass
from typing import Any

from app.domain.in_transit_execution import CURRENT_EXECUTION_SESSION_STATUSES


@dataclass(frozen=True)
class IndexDefinition:
    collection: str
    name: str
    fields: tuple[tuple[str, int], ...]
    unique: bool
    purpose: str
    priority: str = "P0"
    partial_filter: dict[str, Any] | None = None


def _i(collection, name, fields, *, unique=False, purpose, priority="P0", partial=None):
    return IndexDefinition(collection, name, tuple(fields), unique, purpose, priority, partial)


# Partial filters deliberately mirror Phase 1 status vocabularies.
_MANIFEST = (
    _i("tenants", "uq_tenants_id", (("id", 1),), unique=True, purpose="Canonical tenant identity"),
    _i("users", "uq_users_email", (("email", 1),), unique=True, purpose="Normalized login email"),
    _i("users", "uq_users_tenant_id_id", (("tenant_id", 1), ("id", 1)), unique=True, purpose="Tenant user identity"),
    *(_i(c, f"uq_{c}_tenant_id_id", (("tenant_id", 1), ("id", 1)), unique=True, purpose="Tenant-scoped entity identity") for c in (
        "loads","drivers","trucks","documents","audit_events","load_passports","rate_confirmation_extractions",
        "party_verification_cases","execution_eligibility_cases","pickup_release_cases","execution_sessions",
        "execution_events","execution_exceptions","invoice_readiness_cases","invoice_packages","invoices","assumptions",
        "operations","outbox_events","reconciliation_items")),
    _i("trucks", "uq_trucks_tenant_truck_number", (("tenant_id",1),("truck_number",1)), unique=True, purpose="Truck number uniqueness"),
    _i("load_passports", "uq_load_passports_tenant_load", (("tenant_id",1),("load_id",1)), unique=True, purpose="One passport per load"),
    _i("rate_confirmation_extractions", "uq_rc_tenant_document_revision", (("tenant_id",1),("document_id",1),("revision",1)), unique=True, purpose="One extraction revision per document"),
    _i("party_verification_cases", "uq_party_tenant_load", (("tenant_id",1),("load_id",1)), unique=True, purpose="One party case per load, matching create semantics"),
    _i("execution_eligibility_cases", "uq_eligibility_tenant_load", (("tenant_id",1),("load_id",1)), unique=True, purpose="One eligibility case per load, matching create semantics"),
    _i("pickup_release_cases", "uq_pickup_active_tenant_load", (("tenant_id",1),("load_id",1)), unique=True, partial={"status":{"$in":["draft","review_pending","review_required","blocked","release_ready","released","exception"]}}, purpose="One active pickup release per load"),
    _i("execution_sessions", "uq_execution_nonterminal_tenant_load", (("tenant_id",1),("load_id",1)), unique=True, partial={"status":{"$in":sorted(CURRENT_EXECUTION_SESSION_STATUSES)}}, purpose="One non-terminal execution per load"),
    _i("invoice_readiness_cases", "uq_readiness_active_tenant_load", (("tenant_id",1),("load_id",1)), unique=True, partial={"status":{"$in":["draft","review_required","blocked","reopened","ready","approved"]}}, purpose="One current invoice authority per load"),
    _i("invoice_packages", "uq_packages_tenant_readiness", (("tenant_id",1),("readiness_case_id",1)), unique=True, purpose="One package per readiness authority"),
    _i("invoices", "uq_invoices_tenant_readiness", (("tenant_id",1),("readiness_case_id",1)), unique=True, partial={"readiness_case_id":{"$exists":True}}, purpose="One invoice per Phase 1G authority"),
    _i("operations", "uq_operations_idempotency_identity", (("tenant_id",1),("operation_type",1),("target_type",1),("target_id",1),("idempotency_key",1)), unique=True, partial={"idempotency_key":{"$type":"string"}}, purpose="Tenant and command scoped supplied-key idempotency identity"),
    _i("outbox_events", "uq_outbox_operation_event_aggregate", (("tenant_id",1),("operation_id",1),("event_type",1),("aggregate_type",1),("aggregate_id",1)), unique=True, purpose="One required event per operation aggregate boundary"),
    _i("reconciliation_items", "uq_reconciliation_issue", (("tenant_id",1),("operation_id",1),("reason_code",1),("entity_type",1),("entity_id",1)), unique=True, purpose="Deduplicated operation reconciliation issue"),
    _i("audit_events", "ix_audit_tenant_operation_time", (("tenant_id",1),("operation_id",1),("timestamp",1)), purpose="Operation timeline", priority="P1"),
    _i("execution_events", "ix_execution_events_session_time", (("tenant_id",1),("execution_session_id",1),("occurred_at",1),("id",1)), purpose="Execution chronology", priority="P1"),
    _i("execution_exceptions", "ix_execution_exceptions_open_queue", (("tenant_id",1),("status",1),("sla_due_at",1)), purpose="Open exception queue", priority="P1", partial={"status":{"$in":["open","acknowledged"]}}),
    _i("documents", "ix_documents_tenant_load_type", (("tenant_id",1),("load_id",1),("doc_type",1)), purpose="Load evidence lookup", priority="P1"),
    _i("operations", "ix_operations_tenant_status_updated", (("tenant_id",1),("status",1),("updated_at",1)), purpose="Stuck operation and reconciliation scan", priority="P1"),
    _i("outbox_events", "ix_outbox_claim_queue", (("tenant_id",1),("status",1),("next_attempt_at",1),("claim_expires_at",1)), purpose="Pending, retry, and expired-lease worker claim queue", priority="P1"),
    _i("reconciliation_items", "ix_reconciliation_open_queue", (("tenant_id",1),("status",1),("severity",1),("created_at",1)), purpose="Open reconciliation work queue", priority="P1", partial={"status":{"$in":["open","acknowledged"]}}),
    _i("loads", "ix_loads_tenant_stage_updated", (("tenant_id",1),("stage",1),("updated_at",-1)), purpose="Operations load queue", priority="P2"),
)


def expected_indexes() -> tuple[IndexDefinition, ...]:
    return tuple(_MANIFEST)


def compare_indexes(observed: dict[str, list[dict[str, Any]]], limit: int = 200) -> dict[str, Any]:
    """Compare bounded listIndexes-like metadata without changing a database."""
    missing=[]; mismatched=[]
    for expected in _MANIFEST:
        actual=next((x for x in observed.get(expected.collection, []) if x.get("name")==expected.name), None)
        if actual is None: missing.append({"collection":expected.collection,"name":expected.name,"priority":expected.priority})
        elif (tuple(tuple(v) for v in actual.get("fields", actual.get("key", []))) != expected.fields
              or bool(actual.get("unique",False)) != expected.unique
              or actual.get("partial_filter", actual.get("partialFilterExpression")) != expected.partial_filter):
            mismatched.append({"collection":expected.collection,"name":expected.name})
    expected_names={(x.collection,x.name) for x in _MANIFEST}
    unexpected=[{"collection":c,"name":x.get("name","")} for c, xs in sorted(observed.items()) for x in xs if (c,x.get("name")) not in expected_names and x.get("name")!="_id_"]
    return {"missing":missing[:limit],"mismatched":mismatched[:limit],"unexpected":unexpected[:limit],"truncated":any(len(x)>limit for x in (missing,mismatched,unexpected))}
