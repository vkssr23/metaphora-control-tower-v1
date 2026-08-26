"""Append-only, idempotent writer for dispatch-authorization shadow evaluations.

Idempotency does NOT depend on the custom index declared in
app.infrastructure.index_manifest - that manifest is explicitly never
auto-applied (see its own module docstring), so relying on it alone would
leave this collection without real idempotency until a separately gated
index migration is run. Instead, the document's own Mongo `_id` is set to
a deterministic hash of the full decision-relevant input - tenant, load,
subject, decision, reason codes, load version, evaluator version,
normalized source ids/versions, and evidence freshness - relying on the
`_id` uniqueness every Mongo collection already enforces by default, with
no migration required. A repeated call with identical input therefore
always collides on `_id` and is replayed (the existing document is
returned) rather than duplicated; a call where any of that input changed
- including source versions or freshness, even if the resulting decision
happens to be unchanged - gets a new `_id` and a new append-only record.
The manifest's compound index is kept for query-time lookups once its
own migration is separately applied; it is not what correctness rests on.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from app.domain.dispatch_authorization import DispatchOutcome
from app.runtime import now_iso
from app.schemas.dispatch_authorization import DispatchAuthorizationEvaluation


def _normalized_sources(sources: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    normalized = [
        {"source": str(s.get("source", "")), "id": str(s.get("id", "")), "version": str(s.get("version", ""))}
        for s in sources
    ]
    return sorted(normalized, key=lambda s: (s["source"], s["id"]))


def compute_deterministic_id(*, tenant_id: str, load_id: str, subject: str, decision: str,
                             reason_codes: Sequence[str], load_version: str, evaluator_version: str,
                             sources: Sequence[Mapping[str, Any]], evidence_freshness: str) -> str:
    canonical = json.dumps(
        {
            "tenant_id": tenant_id, "load_id": load_id, "subject": subject, "decision": decision,
            "reason_codes": sorted(reason_codes), "load_version": load_version,
            "evaluator_version": evaluator_version, "sources": _normalized_sources(sources),
            "evidence_freshness": evidence_freshness,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def record_evaluation(collection, *, tenant_id: str, load_id: str, subject: str,
                            outcome: DispatchOutcome, load_version: str,
                            sources: Sequence[Mapping[str, Any]], evidence_freshness: str,
                            mode: str) -> dict[str, Any]:
    deterministic_id = compute_deterministic_id(
        tenant_id=tenant_id, load_id=load_id, subject=subject, decision=outcome.decision.value,
        reason_codes=outcome.reason_codes, load_version=load_version or "", evaluator_version=outcome.evaluator_version,
        sources=sources, evidence_freshness=evidence_freshness,
    )
    record = DispatchAuthorizationEvaluation(
        id=f"DAE_{deterministic_id[:24]}", tenant_id=tenant_id, load_id=load_id, subject=subject,
        decision=outcome.decision.value, evaluator_version=outcome.evaluator_version,
        load_version=load_version or "", reason_codes=list(outcome.reason_codes),
        sources=list(sources), evidence_freshness=evidence_freshness, mode=mode,
        evaluated_at=now_iso(), input_hash=deterministic_id,
    )
    payload = record.model_dump(mode="json")
    try:
        await collection.insert_one({**payload, "_id": deterministic_id})
    except Exception:
        existing = await collection.find_one({"_id": deterministic_id})
        if existing is not None:
            existing.pop("_id", None)
            return existing
        raise
    return payload
