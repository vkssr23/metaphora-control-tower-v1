from fastapi import Depends, HTTPException, Query
from app.application.action_center_service import refresh_tenant, serialize, sort_key
from app.audit import begin_audit
from app.domain.action_center import ACTIVE_STATUSES
from app.infrastructure.action_center_projection import acknowledge
from app.schemas.action_center import AcknowledgeAction, ActionCategory, ActionSeverity, OwnerRole
from app.schemas.audit import AuditEntityType
from app.tenant import require_tenant_id
from app.permissions import enforce_action_acknowledgement
from app.application.action_center_service import IncompleteSourceSnapshot

def register_action_center_routes(api, db, get_current_user):
    async def _refresh(user):
        try:return await refresh_tenant(db,require_tenant_id(user))
        except IncompleteSourceSnapshot: raise HTTPException(503,"Action Center source snapshot is incomplete; existing projection was preserved")
        except Exception: raise HTTPException(503,"Action Center projection refresh unavailable")

    @api.get("/action-center")
    async def list_actions(status: str="active", severity: ActionSeverity|None=None, category: ActionCategory|None=None,
                           owner_role: OwnerRole|None=None, load_id: str|None=None, acknowledged: bool|None=None,
                           offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200),user=Depends(get_current_user)):
        tenant=require_tenant_id(user); refreshed=await _refresh(user)
        if status not in {"active","open","acknowledged","resolved","all"}:raise HTTPException(422,"Unsupported status filter")
        query={"tenant_id":tenant}
        if status=="active":query["status"]={"$in":list(ACTIVE_STATUSES)}
        elif status!="all":query["status"]=status
        if severity:query["severity"]=severity
        if category:query["category"]=category
        if owner_role:query["owner_role"]=owner_role
        if load_id:query["load_id"]=load_id
        if acknowledged is not None:query["status"]="acknowledged" if acknowledged else "open"
        rows=await db.action_items.find(query,{"_id":0}).to_list(5000);rows.sort(key=sort_key)
        return {"items":[serialize(x) for x in rows[offset:offset+limit]],"total":len(rows),"offset":offset,"limit":limit,"refreshed_at":refreshed}

    @api.get("/action-center/summary")
    async def summary(user=Depends(get_current_user)):
        tenant=require_tenant_id(user);refreshed=await _refresh(user)
        rows=await db.action_items.find({"tenant_id":tenant,"status":{"$in":list(ACTIVE_STATUSES)}},{"_id":0}).to_list(5000)
        return {"total":len(rows),"open":sum(x.get("status")=="open" for x in rows),"acknowledged":sum(x.get("status")=="acknowledged" for x in rows),
                "by_severity":{k:sum(x.get("severity")==k for x in rows) for k in ("critical","high","medium","low")},
                "by_category":{k:sum(x.get("category")==k for x in rows) for k in ("execution","safety","fraud_risk","documents","finance","reconciliation","platform_integrity")},"refreshed_at":refreshed}

    @api.get("/action-center/{item_id}")
    async def detail(item_id:str,user=Depends(get_current_user)):
        tenant=require_tenant_id(user);await _refresh(user);item=await db.action_items.find_one({"tenant_id":tenant,"id":item_id},{"_id":0})
        if not item:raise HTTPException(404,"Action item not found")
        return serialize(item)

    @api.post("/action-center/{item_id}/acknowledge")
    async def acknowledge_item(item_id:str,data:AcknowledgeAction,user=Depends(get_current_user)):
        tenant=require_tenant_id(user);await _refresh(user);previous=await db.action_items.find_one({"tenant_id":tenant,"id":item_id},{"_id":0})
        if not previous:raise HTTPException(404,"Action item not found")
        enforce_action_acknowledgement(user,previous)
        audit=await begin_audit(db.audit_events,user,"action_center.acknowledged",AuditEntityType.ACTION_ITEM,item_id,changed_fields=["status","acknowledged_at","acknowledged_by"],previous=previous)
        item,outcome=await acknowledge(db.action_items,tenant,item_id,user["id"],data.version)
        if outcome=="resolved":await audit.rejected("source_condition_resolved");raise HTTPException(409,"Source condition is already resolved")
        if outcome=="conflict":await audit.rejected("version_conflict");raise HTTPException(409,"Action item version conflict")
        if outcome=="not_found":await audit.rejected("not_found");raise HTTPException(404,"Action item not found")
        await audit.succeeded(item)
        return serialize(item)
