"""Bounded, fail-closed Action Center source snapshot and refresh service."""
from dataclasses import dataclass
from datetime import datetime, timezone
from app.domain.action_center import build_candidates, SEVERITIES
from app.infrastructure.action_center_projection import reconcile_projection

SOURCE_COLLECTIONS=("loads","documents","load_passports","party_verification_cases","execution_eligibility_cases","pickup_release_cases","execution_sessions","execution_exceptions","invoice_readiness_cases","accessorials","reconciliation_items","production_integrity_findings")
SOURCE_RECORD_CAP=5000

class IncompleteSourceSnapshot(RuntimeError): pass

@dataclass(frozen=True)
class SourceSnapshot:
    records: tuple[dict,...]
    complete: bool

async def load_source_snapshot(collection, tenant_id, cap=SOURCE_RECORD_CAP):
    records=await collection.find({"tenant_id":tenant_id},{"_id":0}).to_list(cap+1)
    return SourceSnapshot(tuple(records[:cap]),len(records)<=cap)

async def refresh_tenant(db, tenant_id):
    snapshot={}
    for name in SOURCE_COLLECTIONS:
        result=await load_source_snapshot(getattr(db,name),tenant_id,SOURCE_RECORD_CAP)
        if not result.complete:
            raise IncompleteSourceSnapshot("Authoritative source snapshot is incomplete")
        snapshot[name]=list(result.records)
    candidates=build_candidates(snapshot)
    await reconcile_projection(db.action_items,tenant_id,candidates)
    return datetime.now(timezone.utc).isoformat()

def serialize(item, now=None):
    now=now or datetime.now(timezone.utc)
    try:first=datetime.fromisoformat(item["first_detected_at"].replace("Z","+00:00"));age=max(0,int((now-first).total_seconds()))
    except (KeyError,TypeError,ValueError):age=0
    allowed=("id","source_type","source_id","load_id","reason_code","category","severity","status","title","summary","owner_role","first_detected_at","last_detected_at","acknowledged_at","acknowledged_by","resolved_at","recommended_action_code","recommended_action_label","entity_type","entity_id","evidence_refs","supporting_reasons","projection_version","version")
    return {**{k:item.get(k) for k in allowed},"age_seconds":age}

def sort_key(item):
    return (SEVERITIES.index(item.get("severity")) if item.get("severity") in SEVERITIES else 99, item.get("status")!="open", item.get("first_detected_at", ""), item.get("id",""))
