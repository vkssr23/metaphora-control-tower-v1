"""Conservative audit-first Phase 1E pre-invalidation used by upstream mutations."""
from fastapi import HTTPException
from app.audit import begin_audit
from app.schemas.audit import AuditEntityType
from app.tenant import tenant_filter
from app.domain.pickup_release import revoke_authorization,utc_now

async def preinvalidate_pickup_release(db,user,load_id,changed_fields):
    collection=getattr(db,"pickup_release_cases",None)
    if collection is None: return []
    cases=await collection.find(tenant_filter(user,{"load_id":load_id,"status":{"$in":["release_ready","released"]}}),{"_id":0}).sort([("updated_at",1),("id",1)]).to_list(50)
    for case in cases:
        now=utc_now(); audit=await begin_audit(db.audit_events,user,"pickup_release.material_change_invalidated",AuditEntityType.PICKUP_RELEASE_CASE,case["id"],changed_fields=list(changed_fields)+["status","version"],previous=case)
        status="review_pending"; custody=case.get("custody_state","not_authorized")
        if case["status"]=="released":
            passport=await db.load_passports.find_one(tenant_filter(user,{"id":case["passport_id"]}),{"_id":0}); auth=(passport or {}).get("pickup_authorization") or {}
            if auth.get("status")=="active":
                revoked=revoke_authorization(auth,user,"material_change_after_release",now)
                pr=await db.load_passports.update_one(tenant_filter(user,{"id":passport["id"],"version":passport["version"],"pickup_authorization.status":"active"}),{"$set":{"pickup_authorization":revoked,"status":"review_pending","version":passport["version"]+1,"updated_at":now,"updated_by":user["id"]}})
                if not pr.matched_count: await audit.rejected("passport_version_conflict"); raise HTTPException(409,"Pickup authorization changed concurrently; upstream mutation was not applied")
            status="exception"; custody="exception"
        update={"status":status,"verdict":"pending","version":case["version"]+1,"updated_at":now,"updated_by":user["id"],"last_material_change_at":now,"blocking_reasons":sorted(set(case.get("blocking_reasons",[]))|{"prerequisite_version_changed"}),"custody_state":custody}
        result=await collection.update_one(tenant_filter(user,{"id":case["id"],"status":case["status"],"version":case["version"]}),{"$set":update})
        if not result.matched_count: await audit.rejected("version_conflict"); raise HTTPException(409,"Pickup release changed concurrently; upstream mutation was not applied")
        await audit.succeeded({"id":case["id"],"load_id":load_id,"status":status,"version":update["version"]})
    return cases

async def preinvalidate_pickup_for_execution_snapshot(db,user,snapshot_field,entity_id,changed_fields):
    collection=getattr(db,"execution_eligibility_cases",None)
    if collection is None: return []
    cases=await collection.find(tenant_filter(user,{f"{snapshot_field}.id":entity_id,"status":"eligible"}),{"_id":0}).sort([("updated_at",1),("id",1)]).to_list(100)
    for case in cases: await preinvalidate_pickup_release(db,user,case["load_id"],changed_fields)
    return cases
