"""Pure, server-controlled Phase 2C mutation impact policy.

This module decides *what* is affected.  It deliberately performs no I/O and
does not decide whether any workflow is positively approved.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence

POLICY_VERSION = "mutation-impact-v1"
MAX_CHANGED_FIELDS = 64
MAX_IMPACTS = 16


class SourceEntityType(StrEnum):
    LOAD = "load"
    DOCUMENT = "document"
    RATE_CONFIRMATION = "rate_confirmation"
    PARTY_VERIFICATION = "party_verification"
    EXECUTION_ELIGIBILITY = "execution_eligibility"
    PICKUP_RELEASE = "pickup_release"
    EXECUTION_SESSION = "execution_session"
    INVOICE_READINESS = "invoice_readiness"
    INVOICE = "invoice"


class MutationType(StrEnum):
    LOAD_UPDATED = "load.updated"
    LOAD_STAGE_CHANGED = "load.stage_changed"
    DOCUMENT_ADDED = "document.added"
    RATE_CONFIRMATION_ACCEPTED = "rate_confirmation.accepted"
    RATE_CONFIRMATION_SUPERSEDED = "rate_confirmation.superseded"
    EXECUTION_PLAN_AMENDED = "execution.plan_amended"
    INVOICE_READINESS_FINANCIAL_BASIS_CHANGED = "invoice_readiness.financial_basis_changed"


class TargetDomain(StrEnum):
    LOAD_PASSPORT = "load_passport"
    PARTY_VERIFICATION = "party_verification"
    EXECUTION_ELIGIBILITY = "execution_eligibility"
    PICKUP_RELEASE = "pickup_release"
    EXECUTION_SESSION = "execution_session"
    INVOICE_READINESS = "invoice_readiness"
    RECONCILIATION = "reconciliation"


class ImpactAction(StrEnum):
    INVALIDATE = "INVALIDATE"
    REOPEN = "REOPEN"
    RECALCULATE = "RECALCULATE"
    REVERIFY = "REVERIFY"
    REVOKE = "REVOKE"
    MATERIAL_CHANGE = "MATERIAL_CHANGE"
    RECONCILE = "RECONCILE"
    NO_ACTION = "NO_ACTION"


# Canonical fields are taken from the actual Phase 1A/1C/1D policies.
LOAD_MATERIAL_FIELDS = frozenset({
    "rate", "miles", "pickup_address", "pickup_city", "pickup_state",
    "pickup_zip", "pickup_appt", "delivery_address", "delivery_city",
    "delivery_state", "delivery_zip", "delivery_appt", "broker", "customer",
    "commodity", "weight", "equipment_type", "driver_id", "truck_id",
    "rate_con_number",
})
LOAD_NON_MATERIAL_FIELDS = frozenset({
    "notes", "risk", "eta", "updated_at", "rpm", "fuel_cost", "tolls",
    "lumper", "driver_pay", "factoring_fee", "other_expenses",
})
PARTY_LOAD_FIELDS = frozenset({
    "broker", "customer", "pickup_address", "pickup_city", "pickup_state",
    "pickup_zip", "pickup_appt", "rate_con_number", "equipment_type",
    "commodity", "weight", "driver_id", "truck_id",
})
EXECUTION_LOAD_FIELD_TYPES = {
    "driver_id": "driver_assignment", "truck_id": "truck_assignment",
    "equipment_type": "equipment", "commodity": "commodity", "weight": "weight",
    "pickup_address": "appointment", "pickup_city": "appointment",
    "pickup_state": "appointment", "pickup_zip": "appointment",
    "pickup_appt": "appointment", "delivery_address": "appointment",
    "delivery_city": "appointment", "delivery_state": "appointment",
    "delivery_zip": "appointment", "delivery_appt": "appointment", "miles": "mileage",
}
BILLING_DOCUMENT_TYPES = frozenset({"pod", "rate_con", "bol", "lumper", "other", "invoice"})
PARTY_DOCUMENT_TYPES = {"rate_con": "rate_confirmation", "insurance": "insurance_evidence"}


@dataclass(frozen=True)
class Impact:
    target_domain: TargetDomain
    action: ImpactAction
    reason_code: str
    order: int
    materiality: str = "material"
    requires_current_record: bool = True
    requires_reconciliation_on_race: bool = True
    change_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class MutationImpactPlan:
    plan_id: str
    policy_version: str
    source_entity_type: SourceEntityType
    source_entity_id: str
    mutation_type: MutationType
    changed_fields: tuple[str, ...]
    unknown_fields: tuple[str, ...]
    impacts: tuple[Impact, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _different(old: Mapping[str, Any], new: Mapping[str, Any], field: str) -> bool:
    # Missing and None are equivalent in the existing optional canonical schema.
    return old.get(field) != new.get(field)


def derive_changed_fields(old: Mapping[str, Any], proposed: Mapping[str, Any], fields: Sequence[str] | None = None) -> tuple[str, ...]:
    """Derive changes from authoritative values, never a client assertion."""
    candidates = set(fields) if fields is not None else set(old) | set(proposed)
    changed = sorted(field for field in candidates if _different(old, proposed, field))
    if len(changed) > MAX_CHANGED_FIELDS:
        raise ValueError("mutation changed-field set exceeds bounded policy")
    return tuple(changed)


def _impact(domain: TargetDomain, action: ImpactAction, reason: str, order: int, change_types=()) -> Impact:
    return Impact(domain, action, reason, order, change_types=tuple(sorted(set(change_types))))


def _load_impacts(changed: set[str]) -> list[Impact]:
    material = changed & LOAD_MATERIAL_FIELDS
    unknown = changed - LOAD_MATERIAL_FIELDS - LOAD_NON_MATERIAL_FIELDS
    if not material and not unknown:
        return []
    # Unknown canonical fields fail closed rather than silently selecting no action.
    reason = "load_material_fields_changed" if material else "load_unknown_fields_require_review"
    impacts = [
        _impact(TargetDomain.PICKUP_RELEASE, ImpactAction.REVOKE, reason, 10, material or unknown),
        _impact(TargetDomain.LOAD_PASSPORT, ImpactAction.INVALIDATE, reason, 20, material or unknown),
    ]
    if material & PARTY_LOAD_FIELDS or unknown:
        impacts.append(_impact(TargetDomain.PARTY_VERIFICATION, ImpactAction.REVERIFY, reason, 30, material & PARTY_LOAD_FIELDS or unknown))
    execution_types = {EXECUTION_LOAD_FIELD_TYPES[f] for f in material if f in EXECUTION_LOAD_FIELD_TYPES}
    if execution_types or unknown:
        impacts.append(_impact(TargetDomain.EXECUTION_ELIGIBILITY, ImpactAction.INVALIDATE, reason, 40, execution_types or unknown))
    impacts.append(_impact(TargetDomain.EXECUTION_SESSION, ImpactAction.MATERIAL_CHANGE, reason, 50, material or unknown))
    if material & {"rate", "rate_con_number"} or unknown:
        impacts.append(_impact(TargetDomain.INVOICE_READINESS, ImpactAction.REOPEN, "invoice_basis_changed", 60, material & {"rate", "rate_con_number"} or unknown))
    return impacts


def _document_impacts(doc_type: str) -> list[Impact]:
    impacts: list[Impact] = []
    party_change = PARTY_DOCUMENT_TYPES.get(doc_type)
    if party_change:
        impacts.extend([
            _impact(TargetDomain.PICKUP_RELEASE, ImpactAction.REVOKE, "document_prerequisite_changed", 10, [party_change]),
            _impact(TargetDomain.LOAD_PASSPORT, ImpactAction.INVALIDATE, "document_prerequisite_changed", 20, [party_change]),
            _impact(TargetDomain.PARTY_VERIFICATION, ImpactAction.REVERIFY, "document_prerequisite_changed", 30, [party_change]),
            _impact(TargetDomain.EXECUTION_ELIGIBILITY, ImpactAction.INVALIDATE, "document_prerequisite_changed", 40, ["rate_confirmation" if doc_type == "rate_con" else "party_verification"]),
        ])
    if doc_type in BILLING_DOCUMENT_TYPES:
        impacts.append(_impact(TargetDomain.INVOICE_READINESS, ImpactAction.REOPEN, "billing_document_changed", 60, [doc_type]))
    return impacts


def _fixed_impacts(mutation: MutationType) -> list[Impact]:
    if mutation in {MutationType.RATE_CONFIRMATION_ACCEPTED, MutationType.RATE_CONFIRMATION_SUPERSEDED}:
        reason = "rate_confirmation_identity_changed"
        return [
            _impact(TargetDomain.PICKUP_RELEASE, ImpactAction.REVOKE, reason, 10, ["rate_confirmation"]),
            _impact(TargetDomain.LOAD_PASSPORT, ImpactAction.INVALIDATE, reason, 20, ["rate_confirmation"]),
            _impact(TargetDomain.PARTY_VERIFICATION, ImpactAction.REVERIFY, reason, 30, ["rate_confirmation"]),
            _impact(TargetDomain.EXECUTION_ELIGIBILITY, ImpactAction.INVALIDATE, reason, 40, ["rate_confirmation"]),
            _impact(TargetDomain.INVOICE_READINESS, ImpactAction.REOPEN, "rate_confirmation_changed", 60, [mutation.value]),
        ]
    if mutation == MutationType.EXECUTION_PLAN_AMENDED:
        return [_impact(TargetDomain.INVOICE_READINESS, ImpactAction.REOPEN, "delivery_basis_changed", 10, [mutation.value])]
    if mutation == MutationType.INVOICE_READINESS_FINANCIAL_BASIS_CHANGED:
        return [_impact(TargetDomain.INVOICE_READINESS, ImpactAction.RECALCULATE, "invoice_basis_changed", 10)]
    return []


def plan_mutation(source_entity_type: SourceEntityType | str, source_entity_id: str, mutation_type: MutationType | str, *, old_state: Mapping[str, Any] | None = None, proposed_state: Mapping[str, Any] | None = None, relevant_fields: Sequence[str] | None = None, context: Mapping[str, Any] | None = None) -> MutationImpactPlan:
    source = SourceEntityType(source_entity_type); mutation = MutationType(mutation_type)
    if not source_entity_id or len(source_entity_id) > 128:
        raise ValueError("source entity id is required and bounded")
    changed = derive_changed_fields(old_state or {}, proposed_state or {}, relevant_fields) if old_state is not None or proposed_state is not None else ()
    unknown: tuple[str, ...] = ()
    if mutation == MutationType.LOAD_UPDATED:
        unknown = tuple(sorted(set(changed) - LOAD_MATERIAL_FIELDS - LOAD_NON_MATERIAL_FIELDS))
        impacts = _load_impacts(set(changed))
    elif mutation == MutationType.DOCUMENT_ADDED:
        doc_type = str((context or {}).get("document_type", ""))
        impacts = _document_impacts(doc_type)
        changed = (doc_type,) if doc_type else ()
    elif mutation == MutationType.LOAD_STAGE_CHANGED:
        old_stage, new_stage = (old_state or {}).get("stage"), (proposed_state or {}).get("stage")
        impacts = [_impact(TargetDomain.INVOICE_READINESS, ImpactAction.REOPEN, "delivery_basis_changed", 10, ["load_stage"])] if old_stage == "Delivered" and new_stage != "Delivered" else []
    else:
        impacts = _fixed_impacts(mutation)
    impacts = sorted(impacts, key=lambda item: (item.order, item.target_domain.value, item.reason_code))
    if len(impacts) > MAX_IMPACTS:
        raise ValueError("impact set exceeds bounded policy")
    fingerprint_payload = {"policy_version": POLICY_VERSION, "source": source.value, "source_id": source_entity_id, "mutation": mutation.value, "changed_fields": changed, "impacts": [asdict(item) for item in impacts]}
    plan_id = "mip_" + hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    return MutationImpactPlan(plan_id, POLICY_VERSION, source, source_entity_id, mutation, tuple(changed), unknown, tuple(impacts))


def has_impact(plan: MutationImpactPlan, target: TargetDomain | str) -> bool:
    target = TargetDomain(target)
    return any(item.target_domain == target for item in plan.impacts)


def impact_for(plan: MutationImpactPlan, target: TargetDomain | str) -> Impact | None:
    target = TargetDomain(target)
    return next((item for item in plan.impacts if item.target_domain == target), None)
