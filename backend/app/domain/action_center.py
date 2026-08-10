"""Pure deterministic Phase 2F Action Center policy.

Action candidates are projections only.  No function in this module mutates, or
authorizes a mutation of, an operational source record.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from typing import Any, Iterable

POLICY_VERSION = "action-center-v1"
CATEGORIES = frozenset({"execution", "safety", "fraud_risk", "documents", "finance", "reconciliation", "platform_integrity"})
SEVERITIES = ("critical", "high", "medium", "low")
OWNER_ROLES = frozenset({"operations", "safety", "finance", "admin"})
ACTIVE_STATUSES = frozenset({"open", "acknowledged"})

REASON_POLICY = {
    "pickup_authorization_revoked": ("execution", "high", "operations", "Pickup authorization revoked", "Review pickup prerequisites", "review_pickup_release"),
    "pickup_release_blocked": ("execution", "high", "operations", "Pickup release blocked", "Review pickup release findings", "review_pickup_release"),
    "party_verification_required": ("fraud_risk", "high", "safety", "Party verification required", "Review party verification evidence", "review_party_verification"),
    "execution_not_eligible": ("safety", "high", "safety", "Execution eligibility blocked", "Review eligibility prerequisites", "review_execution_eligibility"),
    "active_execution_exception": ("execution", "high", "operations", "Execution exception requires attention", "Review the execution exception", "review_execution_exception"),
    "detention_active": ("execution", "high", "operations", "Detention requires attention", "Review detention evidence", "review_execution_exception"),
    "delivery_delay": ("execution", "high", "operations", "Delivery delay requires attention", "Review current execution progress", "review_execution_session"),
    "pod_missing_after_delivery": ("documents", "high", "operations", "POD required before invoicing", "Record current POD evidence", "review_documents"),
    "invoice_readiness_blocked": ("finance", "medium", "finance", "Invoice readiness blocked", "Review invoice prerequisites", "review_invoice_readiness"),
    "accessorial_approval_required": ("finance", "medium", "finance", "Accessorial approval required", "Review pending accessorial", "review_invoice_readiness"),
    "operation_reconciliation_required": ("reconciliation", "high", "admin", "Reconciliation requires attention", "Open the reconciliation workflow", "review_reconciliation"),
    "platform_integrity_critical": ("platform_integrity", "critical", "admin", "Production integrity finding requires attention", "Review the integrity finding", "review_integrity"),
    "document_evidence_incomplete": ("documents", "medium", "admin", "Document evidence requires reconciliation", "Review document evidence metadata", "review_documents"),
}

@dataclass(frozen=True)
class Candidate:
    source_type: str
    source_id: str
    reason_code: str
    entity_type: str
    entity_id: str
    load_id: str | None
    category: str
    severity: str
    owner_role: str
    title: str
    summary: str
    recommended_action_code: str
    recommended_action_label: str
    evidence_refs: tuple[dict[str, str], ...] = ()
    supporting_reasons: tuple[str, ...] = ()

    @property
    def active_identity(self) -> str:
        raw = "|".join((self.source_type, self.source_id, self.reason_code, self.entity_type, self.entity_id))
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def fingerprint(self) -> str:
        raw = repr((self.active_identity, self.severity, self.summary, self.evidence_refs, self.supporting_reasons))
        return hashlib.sha256(raw.encode()).hexdigest()

    def document(self) -> dict[str, Any]:
        value = asdict(self)
        value.update(active_identity=self.active_identity, source_fingerprint=self.fingerprint, projection_version=POLICY_VERSION)
        value["evidence_refs"] = list(self.evidence_refs)
        value["supporting_reasons"] = list(self.supporting_reasons)
        return value

def _candidate(reason: str, source_type: str, source_id: str, entity_type: str, entity_id: str,
               load_id: str | None, summary: str, evidence: Iterable[dict[str, str]] = (), supporting=(), severity=None) -> Candidate:
    category, default_severity, owner, title, action_label, action_code = REASON_POLICY[reason]
    return Candidate(source_type, source_id, reason, entity_type, entity_id, load_id, category,
                     severity or default_severity, owner, title, str(summary)[:500], action_code,
                     action_label, tuple(evidence)[:20], tuple(sorted(set(supporting)))[:20])

def detect_pickup_actions(cases, passports):
    passports_by_load = {x.get("load_id"): x for x in passports}
    out=[]
    for case in cases:
        status=case.get("status"); load_id=case.get("load_id"); passport=passports_by_load.get(load_id) or {}
        auth=passport.get("pickup_authorization") or {}
        if auth.get("status") == "revoked":
            out.append(_candidate("pickup_authorization_revoked", "pickup_release", case["id"], "load", load_id, load_id,
                "Pickup authorization is revoked; authoritative prerequisites must be reviewed.",
                ({"type":"pickup_release","id":case["id"]},{"type":"pickup_authorization","id":auth.get("authorization_id","")}),
                case.get("blocking_reasons",())))
        elif status in {"blocked", "review_required", "revoked", "exception"}:
            out.append(_candidate("pickup_release_blocked", "pickup_release", case["id"], "load", load_id, load_id,
                "The current pickup release case is not releasable.", ({"type":"pickup_release","id":case["id"]},), case.get("blocking_reasons",())))
    return out

def detect_party_actions(cases):
    return [_candidate("party_verification_required", "party_verification", x["id"], "load", x.get("load_id"), x.get("load_id"),
        "Internal party evidence requires review; this is not a fraud confirmation.", ({"type":"party_verification","id":x["id"]},), x.get("blocking_reasons",()),
        "critical" if (x.get("risk_summary") or {}).get("risk_level")=="critical" else None)
        for x in cases if x.get("status") in {"review_pending","review_required","findings_open","blocked","expired","revoked"}]

def detect_eligibility_actions(cases):
    return [_candidate("execution_not_eligible", "execution_eligibility", x["id"], "load", x.get("load_id"), x.get("load_id"),
        "The current eligibility case is not eligible.", ({"type":"execution_eligibility","id":x["id"]},), x.get("blocking_reasons",()))
        for x in cases if x.get("status") in {"review_pending","review_required","blocked","expired","revoked"}]

def detect_execution_actions(sessions, exceptions):
    sessions_by_id={x.get("id"):x for x in sessions}; out=[]
    for x in exceptions:
        if x.get("status") in {"resolved","waived","closed"}: continue
        session=sessions_by_id.get(x.get("execution_session_id")) or {}
        reason="detention_active" if x.get("type") in {"detention_active","detention_exceeds_threshold"} else "active_execution_exception"
        severity=x.get("severity") if x.get("severity") in SEVERITIES else ("medium" if x.get("severity") in {"warning","info"} else None)
        out.append(_candidate(reason,"execution_exception",x["id"],"execution_exception",x["id"],x.get("load_id") or session.get("load_id"),
            "An active execution exception remains open in the source workflow.",({"type":"execution_exception","id":x["id"]},),severity=severity))
    for s in sessions:
        delay=s.get("delay_snapshot") or {}
        if delay.get("delay_state")=="delayed" and not any(c.source_type=="execution_exception" and c.load_id==s.get("load_id") for c in out):
            out.append(_candidate("delivery_delay","execution_session",s["id"],"load",s.get("load_id"),s.get("load_id"),
                "The current manual execution evaluation reports a delivery delay.",({"type":"execution_session","id":s["id"]},),(delay.get("reason_code"),)))
    return out

def detect_document_and_invoice_actions(loads, documents, readiness, accessorials):
    docs_by_load={}
    for d in documents: docs_by_load.setdefault(d.get("load_id"),[]).append(d)
    out=[]
    for load in loads:
        lid=load.get("id"); delivered=load.get("stage") in {"Delivered","Closed"}
        if delivered and not any(d.get("doc_type")=="pod" for d in docs_by_load.get(lid,())):
            out.append(_candidate("pod_missing_after_delivery","load",lid,"load",lid,lid,"The load is delivered but no POD evidence record is present.",({"type":"load","id":lid},)))
    for case in readiness:
        if case.get("status") in {"draft","review_pending","review_required","blocked","reopened"}:
            blockers=case.get("blockers") or case.get("blocking_reasons") or []
            out.append(_candidate("invoice_readiness_blocked","invoice_readiness",case["id"],"load",case.get("load_id"),case.get("load_id"),
                "Invoice readiness remains blocked by authoritative finance prerequisites.",({"type":"invoice_readiness","id":case["id"]},),blockers))
    for item in accessorials:
        if item.get("status") not in {"approved","rejected","waived"}:
            out.append(_candidate("accessorial_approval_required","accessorial",item["id"],"load",item.get("load_id"),item.get("load_id"),
                "An accessorial remains pending in the finance workflow.",({"type":"accessorial","id":item["id"]},)))
    return out

def detect_reconciliation_actions(items):
    return [_candidate("operation_reconciliation_required","reconciliation",x["id"],x.get("entity_type","operation"),x.get("entity_id") or x.get("operation_id"),x.get("load_id"),
        "A durable reconciliation item remains open.",({"type":"reconciliation","id":x["id"]},), (x.get("reason_code"),),
        x.get("severity") if x.get("severity") in SEVERITIES else None) for x in items if x.get("status") in {"open","acknowledged"}]

def detect_integrity_actions(findings):
    out=[]
    for x in findings:
        if x.get("status","open") not in {"open","acknowledged"}: continue
        if x.get("severity") in {"critical","high"}:
            out.append(_candidate("platform_integrity_critical","production_integrity",x.get("id") or x.get("code"),x.get("entity_type") or x.get("collection","record"),x.get("entity_id") or x.get("code"),x.get("load_id"),
                "A persisted production-integrity finding requires administrative review.",({"type":"integrity_finding","id":x.get("id") or x.get("code")},), (x.get("code"),), x.get("severity")))
    return out

def build_candidates(snapshot: dict[str, list[dict]]) -> list[Candidate]:
    candidates=[*detect_pickup_actions(snapshot.get("pickup_release_cases",()),snapshot.get("load_passports",())),
        *detect_party_actions(snapshot.get("party_verification_cases",())),*detect_eligibility_actions(snapshot.get("execution_eligibility_cases",())),
        *detect_execution_actions(snapshot.get("execution_sessions",()),snapshot.get("execution_exceptions",())),
        *detect_document_and_invoice_actions(snapshot.get("loads",()),snapshot.get("documents",()),snapshot.get("invoice_readiness_cases",()),snapshot.get("accessorials",())),
        *detect_reconciliation_actions(snapshot.get("reconciliation_items",())),*detect_integrity_actions(snapshot.get("production_integrity_findings",()))]
    unique={c.active_identity:c for c in candidates}
    return sorted(unique.values(),key=lambda c:(SEVERITIES.index(c.severity),c.reason_code,c.active_identity))
