from datetime import datetime,timezone
from fastapi import HTTPException
from app.audit import begin_audit
from app.schemas.audit import AuditEntityType
from app.tenant import tenant_filter
from app.domain.invoice_readiness import invalidation_plan

def now():return datetime.now(timezone.utc).isoformat()

async def invalidate_invoice_readiness(db,user,load_id,reason,changed_types):
    collection=getattr(db,"invoice_readiness_cases",None)
    if collection is None:return []
    cases=await collection.find(tenant_filter(user,{"load_id":load_id}),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(50)
    changed=[]
    for case in cases:
        try:plan=invalidation_plan(case,reason,changed_types,now(),user["id"])
        except ValueError:raise HTTPException(409,"Invoice creation or issued invoice blocks material billing change")
        if not plan:continue
        audit=await begin_audit(db.audit_events,user,"invoice_readiness.material_change_invalidated",AuditEntityType.INVOICE_READINESS_CASE,case["id"],changed_fields=["status","verdict","version","readiness_items"],previous=case)
        try:r=await collection.update_one(tenant_filter(user,plan["query"]),{"$set":plan["update"]})
        except Exception:await audit.failed("invalidation_failure");raise HTTPException(503,"Invoice readiness invalidation unavailable")
        if not r.matched_count:await audit.rejected("version_conflict");raise HTTPException(409,"Invoice readiness changed concurrently")
        await audit.succeeded({"id":case["id"],"status":plan["update"]["status"],"version":plan["update"]["version"],"reason_code":reason});changed.append(case["id"])
    return changed
