"""Shadow-evaluation wiring for the dispatch-authorization foundation (PR1).

Runs the pure canonical evaluator from app.domain.dispatch_authorization
alongside the real passport-authorization and boundary-stage-transition
decision points, persisting an append-only, tenant-scoped record of what
the evaluator *would* decide plus a matching audit event. This module
never affects the real decision: every call is best-effort and swallows
its own failures, and whether it runs at all makes no difference to the
caller's control flow or response. DISPATCH_GATE_ENFORCED is recorded on
each evaluation for later reference, but PR1 does not read it to alter
behavior - a follow-up change is required to make the evaluator's
decision load-bearing.
"""
from __future__ import annotations

import logging

from app.domain import dispatch_authorization as evaluator
from app.domain.audit_events import build_event, new_operation_id
from app.domain.load_transitions import transition_allowed
from app.infrastructure import dispatch_authorization_store as store
from app.infrastructure import party_verification_client
from app.schemas.audit import AuditEntityType, AuditPhase, AuditSource
from app.schemas.dispatch_authorization import EvaluationSubject, EvidenceFreshness
from app.tenant import require_tenant_id, tenant_filter

logger = logging.getLogger(__name__)


async def _latest_accepted_rate(db, user, load_id):
    docs = await db.documents.find(
        tenant_filter(user, {"load_id": load_id, "doc_type": "rate_con"}), {"_id": 0},
    ).sort([("uploaded_at", -1), ("id", -1)]).to_list(100)
    rate_doc_ids = {d["id"] for d in docs}
    rates = await db.rate_confirmation_extractions.find(
        tenant_filter(user, {"load_id": load_id, "status": "accepted"}), {"_id": 0},
    ).sort([("accepted_at", -1), ("id", -1)]).to_list(100)
    return next((r for r in rates if r.get("document_id") in rate_doc_ids), None)


async def _fetch_verify(settings, rate):
    try:
        return await party_verification_client.fetch_broker_verification(settings, rate)
    except Exception:
        logger.exception("dispatch_authorization shadow evaluation: Verify fetch raised unexpectedly")
        return {"status": "unavailable"}


def _freshness_for(verify_result) -> EvidenceFreshness:
    if verify_result is None:
        return EvidenceFreshness.MISSING
    if verify_result.get("status") == "unavailable":
        return EvidenceFreshness.UNAVAILABLE
    return EvidenceFreshness.CURRENT


def _rate_source(rate):
    if not rate:
        return None
    return {"source": "rate_confirmation_extraction", "id": rate.get("id", ""), "version": str(rate.get("version", ""))}


async def _persist(db, user, *, load_id, subject, outcome, load_version, sources, freshness, gate_enforced):
    tenant_id = require_tenant_id(user)
    sources = [s for s in sources if s is not None]
    try:
        record = await store.record_evaluation(
            db.dispatch_authorization_evaluations, tenant_id=tenant_id, load_id=load_id,
            subject=subject.value, outcome=outcome, load_version=load_version or "", sources=sources,
            evidence_freshness=freshness.value, gate_enforced=gate_enforced,
        )
    except Exception:
        logger.exception("dispatch_authorization shadow evaluation: failed to persist evaluation record")
        return None
    try:
        event = build_event(
            user=user, operation_id=new_operation_id(), phase=AuditPhase.SUCCEEDED,
            action="dispatch_authorization.shadow_evaluated",
            entity_type=AuditEntityType.DISPATCH_AUTHORIZATION_EVALUATION, entity_id=record["id"],
            source=AuditSource.SYSTEM, changed_fields=["load_id", "decision", "subject", "reason_code", "evidence_freshness"],
            new={
                "load_id": load_id, "decision": outcome.decision.value, "subject": subject.value,
                "reason_code": (outcome.reason_codes[0] if outcome.reason_codes else ""),
                "evidence_freshness": freshness.value,
            },
        )
        await db.audit_events.insert_one(dict(event))
    except Exception:
        logger.exception("dispatch_authorization shadow evaluation: failed to write audit event")
    return record


async def shadow_evaluate_passport_authorization(db, settings, user, passport, load, readiness):
    """Best-effort. Never raises; returns None on any internal failure."""
    try:
        rate = await _latest_accepted_rate(db, user, load["id"])
        verify_result = await _fetch_verify(settings, rate)
        outcome = evaluator.evaluate_passport_authorization(verify_result=verify_result, passport=passport, readiness=readiness)
        sources = [
            {"source": "load", "id": load["id"], "version": str(load.get("updated_at", ""))},
            {"source": "load_passport", "id": passport["id"], "version": str(passport.get("version", ""))},
            _rate_source(rate),
        ]
        return await _persist(
            db, user, load_id=load["id"], subject=EvaluationSubject.PASSPORT_AUTHORIZATION, outcome=outcome,
            load_version=str(load.get("updated_at", "")), sources=sources, freshness=_freshness_for(verify_result),
            gate_enforced=bool(getattr(settings, "dispatch_gate_enforced", False)),
        )
    except Exception:
        logger.exception("dispatch_authorization shadow evaluation (passport authorization) failed")
        return None


async def shadow_evaluate_boundary_stage_transition(db, settings, user, load, current_stage, requested_stage, exception_origin=None):
    """Best-effort. Never raises; returns None on any internal failure."""
    try:
        rate = await _latest_accepted_rate(db, user, load["id"])
        verify_result = await _fetch_verify(settings, rate)
        is_allowed = transition_allowed(current_stage, requested_stage, exception_origin)
        outcome = evaluator.evaluate_boundary_stage_transition(
            verify_result=verify_result, current_stage=current_stage.value if current_stage is not None else None,
            requested_stage=requested_stage.value if requested_stage is not None else None,
            transition_is_allowed=is_allowed,
        )
        sources = [
            {"source": "load", "id": load["id"], "version": str(load.get("updated_at", ""))},
            _rate_source(rate),
        ]
        return await _persist(
            db, user, load_id=load["id"], subject=EvaluationSubject.BOUNDARY_STAGE_TRANSITION, outcome=outcome,
            load_version=str(load.get("updated_at", "")), sources=sources, freshness=_freshness_for(verify_result),
            gate_enforced=bool(getattr(settings, "dispatch_gate_enforced", False)),
        )
    except Exception:
        logger.exception("dispatch_authorization shadow evaluation (boundary stage transition) failed")
        return None
