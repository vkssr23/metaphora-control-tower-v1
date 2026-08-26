"""Append-only, idempotent writer for dispatch-authorization shadow evaluations.

Standalone-Mongo-safe: no transactions are available, so idempotent
replay relies on the unique `uq_dispatch_authorization_evaluations_input`
index (tenant_id, load_id, subject, input_hash) declared in
app.infrastructure.index_manifest, plus catching the insert race and
re-reading the winner - the same pattern used by
app.infrastructure.operations.create_or_replay. There is no update path:
a record is either inserted once or, on a replayed identical evaluation,
the existing record is returned unchanged.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from app.domain.dispatch_authorization import DispatchOutcome
from app.runtime import new_id, now_iso
from app.schemas.dispatch_authorization import DispatchAuthorizationEvaluation


def compute_input_hash(*, subject: str, decision: str, reason_codes: Sequence[str],
                        load_version: str, evaluator_version: str) -> str:
    canonical = json.dumps(
        {
            "subject": subject,
            "decision": decision,
            "reason_codes": sorted(reason_codes),
            "load_version": load_version,
            "evaluator_version": evaluator_version,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def record_evaluation(collection, *, tenant_id: str, load_id: str, subject: str,
                            outcome: DispatchOutcome, load_version: str,
                            sources: Sequence[Mapping[str, Any]], evidence_freshness: str,
                            gate_enforced: bool) -> dict[str, Any]:
    input_hash = compute_input_hash(
        subject=subject, decision=outcome.decision.value, reason_codes=outcome.reason_codes,
        load_version=load_version or "", evaluator_version=outcome.evaluator_version,
    )
    record = DispatchAuthorizationEvaluation(
        id=new_id("DAE"), tenant_id=tenant_id, load_id=load_id, subject=subject,
        decision=outcome.decision.value, evaluator_version=outcome.evaluator_version,
        load_version=load_version or "", reason_codes=list(outcome.reason_codes),
        sources=list(sources), evidence_freshness=evidence_freshness, gate_enforced=gate_enforced,
        evaluated_at=now_iso(), input_hash=input_hash,
    )
    doc = record.model_dump(mode="json")
    try:
        await collection.insert_one(dict(doc))
    except Exception:
        existing = await collection.find_one(
            {"tenant_id": tenant_id, "load_id": load_id, "subject": subject, "input_hash": input_hash},
            {"_id": 0},
        )
        if existing is not None:
            return existing
        raise
    return doc
