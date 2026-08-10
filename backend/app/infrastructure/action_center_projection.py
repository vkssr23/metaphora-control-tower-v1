"""Persistence reconciliation for Action Center projection records."""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from app.domain.action_center import ACTIVE_STATUSES, Candidate

def _stamp(now=None): return (now or datetime.now(timezone.utc)).isoformat()
def action_id(identity): return "act_"+hashlib.sha256(identity.encode()).hexdigest()[:24]
class ProjectionConflict(RuntimeError): pass

async def _resolve_source_cleared(collection,tenant_id,current,stamp,max_attempts=3):
    item=current
    for _ in range(max_attempts):
        if item.get("status")=="resolved":return item
        if item.get("status") not in ACTIVE_STATUSES:return item
        result=await collection.update_one({"tenant_id":tenant_id,"id":item["id"],"version":item.get("version",1),"status":{"$in":list(ACTIVE_STATUSES)}},
            {"$set":{"status":"resolved","resolved_at":stamp,"updated_at":stamp,"last_detected_at":stamp},"$inc":{"version":1}})
        if result.matched_count:return await collection.find_one({"tenant_id":tenant_id,"id":item["id"]},{"_id":0})
        item=await collection.find_one({"tenant_id":tenant_id,"id":item["id"]},{"_id":0})
        if not item:return None
    raise ProjectionConflict("Source-derived action resolution could not be persisted")

async def reconcile_projection(collection, tenant_id: str, candidates: list[Candidate], now=None):
    stamp=_stamp(now); existing=await collection.find({"tenant_id":tenant_id},{"_id":0}).to_list(5001)
    if len(existing)>5000:raise ProjectionConflict("Action projection exceeds the pilot reconciliation cap")
    active={x.get("active_identity"):x for x in existing if x.get("status") in ACTIVE_STATUSES}
    expected={x.active_identity:x for x in candidates}
    for identity,candidate in expected.items():
        current=active.get(identity); payload=candidate.document()
        if current:
            update={"$set":{**payload,"last_detected_at":stamp,"updated_at":stamp}}
            if current.get("source_fingerprint")!=payload.get("source_fingerprint"):update["$inc"]={"version":1}
            await collection.update_one({"tenant_id":tenant_id,"id":current["id"],"version":current.get("version",1),"status":{"$in":list(ACTIVE_STATUSES)}},
                update)
        else:
            history=await collection.find({"tenant_id":tenant_id,"active_identity":identity},{"_id":0}).sort("incident_generation",-1).to_list(1)
            generation=max((int(x.get("incident_generation",0)) for x in history),default=0)+1
            incident_identity=f"{identity}:{generation}"
            await collection.insert_one({"id":action_id(incident_identity),"tenant_id":tenant_id,**payload,"incident_generation":generation,
                "status":"open","first_detected_at":stamp,"last_detected_at":stamp,"acknowledged_at":None,"acknowledged_by":None,
                "resolved_at":None,"created_at":stamp,"updated_at":stamp,"version":1})
    for identity,current in active.items():
        if identity not in expected:
            await _resolve_source_cleared(collection,tenant_id,current,stamp)

async def acknowledge(collection, tenant_id, item_id, actor_id, version, now=None):
    item=await collection.find_one({"tenant_id":tenant_id,"id":item_id},{"_id":0})
    if not item:return None,"not_found"
    if item.get("status")=="resolved":return item,"resolved"
    if item.get("status")=="acknowledged":return item,"idempotent"
    if item.get("version")!=version:return item,"conflict"
    stamp=_stamp(now)
    result=await collection.update_one({"tenant_id":tenant_id,"id":item_id,"version":version,"status":"open"},{"$set":{"status":"acknowledged","acknowledged_at":stamp,"acknowledged_by":actor_id,"updated_at":stamp},"$inc":{"version":1}})
    if not result.matched_count:return item,"conflict"
    return await collection.find_one({"tenant_id":tenant_id,"id":item_id},{"_id":0}),"acknowledged"
