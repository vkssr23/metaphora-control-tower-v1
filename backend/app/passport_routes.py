"""Phase 1A tenant-scoped load-passport HTTP workflow."""
import uuid
from fastapi import Depends, HTTPException, Query
from app.audit import begin_audit
from app.domain.load_passports import (CHECKPOINT_ROLES, MATERIAL_LOAD_FIELDS, PRE_PICKUP_STAGES,
    REQUIRED_CHECKPOINT_TYPES, bounded_load_snapshot, calculate_profitability, canonical_hash,
    evaluate_readiness, utc_now)
from app.schemas.audit import AuditEntityType
from app.schemas.passports import (CheckpointStatus, CheckpointType, CheckpointUpdate, EmptyAction,
    PassportCreate, PassportUpdate, ReasonAction)
from app.tenant import tenant_document, tenant_filter
from app.execution_invalidation import preinvalidate_for_load
from app.runtime import settings
from app.dispatch_authorization_shadow import shadow_evaluate_passport_authorization

ADMIN_ROLES={"owner","admin"}; OPERATIONAL_ROLES={"owner","admin","operations","dispatcher"}
ALLOWED={"draft":{"review_pending"},"review_pending":{"approved","blocked"},"blocked":{"review_pending"},"approved":{"pickup_authorized","revoked"},"pickup_authorized":{"revoked"},"revoked":{"review_pending"}}
def _id(prefix): return prefix+uuid.uuid4().hex
def _public(doc):
    if doc: doc=dict(doc); doc.pop("_id",None)
    return doc
def _role(user, roles):
    if user.get("role") not in roles: raise HTTPException(403,"Insufficient permission")
async def _passport(db,user,pid):
    doc=await db.load_passports.find_one(tenant_filter(user,{"id":pid}),{"_id":0})
    if not doc: raise HTTPException(404,"Not found")
    return doc
async def _load(db,user,lid):
    doc=await db.loads.find_one(tenant_filter(user,{"id":lid}),{"_id":0})
    if not doc: raise HTTPException(404,"Not found")
    return doc
async def _references(db,user,load):
    driver=truck=None
    if load.get("driver_id"):
        driver=await db.drivers.find_one(tenant_filter(user,{"id":load["driver_id"]}),{"_id":0})
        if not driver: raise HTTPException(404,"Not found")
    if load.get("truck_id"):
        truck=await db.trucks.find_one(tenant_filter(user,{"id":load["truck_id"]}),{"_id":0})
        if not truck: raise HTTPException(404,"Not found")
    return {"driver_id":load.get("driver_id"),"driver_name":(driver or {}).get("name",""),"truck_id":load.get("truck_id"),"truck_number":(truck or {}).get("truck_number",""),"trailer_identifier":"","assignment_timestamp":utc_now()}
async def _replace(db,audit,user,old,updates,operation):
    updates={**updates,"version":old["version"]+1,"updated_at":utc_now(),"updated_by":user["id"]}
    result=await db.load_passports.update_one(tenant_filter(user,{"id":old["id"],"status":old["status"],"version":old["version"]}),{"$set":updates})
    if not result.matched_count:
        await audit.rejected("version_conflict"); raise HTTPException(409,"Passport changed; reload and retry")
    await audit.succeeded({"id":old["id"],"status":updates.get("status",old["status"]),"version":updates["version"]})
    return await _passport(db,user,old["id"])
def register_passport_routes(api,db,get_current_user):
    @api.get("/load-passports")
    async def list_passports(limit:int=Query(100,ge=1,le=200),user=Depends(get_current_user)):
        return await db.load_passports.find(tenant_filter(user),{"_id":0}).sort("updated_at",-1).to_list(limit)
    @api.get("/load-passports/{passport_id}")
    async def get_passport(passport_id:str,user=Depends(get_current_user)):
        p=await _passport(db,user,passport_id); load=await db.loads.find_one(tenant_filter(user,{"id":p["load_id"]}),{"_id":0}); p["readiness"]=evaluate_readiness(p,load); return p
    @api.get("/loads/{load_id}/passport")
    async def get_load_passport(load_id:str,user=Depends(get_current_user)):
        await _load(db,user,load_id); p=await db.load_passports.find_one(tenant_filter(user,{"load_id":load_id}),{"_id":0})
        if not p: raise HTTPException(404,"Not found")
        p["readiness"]=evaluate_readiness(p,await _load(db,user,load_id)); return p
    @api.post("/loads/{load_id}/passport",status_code=201)
    async def create_passport(load_id:str,data:PassportCreate,user=Depends(get_current_user)):
        _role(user,OPERATIONAL_ROLES); load=await _load(db,user,load_id)
        if await db.load_passports.find_one(tenant_filter(user,{"load_id":load_id}),{"_id":0}): raise HTTPException(409,"An active passport already exists for this load")
        assignment=await _references(db,user,load); assignment["trailer_identifier"]=data.trailer_identifier
        docs=await db.documents.find(tenant_filter(user,{"load_id":load_id,"doc_type":"rate_con"}),{"_id":0}).sort("uploaded_at",-1).to_list(1); rate_doc=docs[0] if docs else None
        assumptions=await db.assumptions.find_one(tenant_filter(user,{"id":"default"}),{"_id":0}) or {}
        now=utc_now(); pid=_id("lps_"); checkpoints=[{"type":k,"status":"pending","blocking":True,"checked_at":None,"checked_by":None,"checked_by_role":None,"reason_code":"","notes":"","evidence_document_ids":[],"expires_at":None,"source":"manual"} for k in REQUIRED_CHECKPOINT_TYPES]
        doc=tenant_document(user,{"id":pid,"load_id":load_id,"version":1,"status":"draft","created_at":now,"updated_at":now,"created_by":user["id"],"updated_by":user["id"],"submitted_at":None,"submitted_by":None,"approved_at":None,"approved_by":None,"approved_version":None,"rejected_at":None,"rejected_by":None,"rejection_reason":"","pickup_authorization":None,"blocking_reasons":[],"required_checkpoint_types":list(REQUIRED_CHECKPOINT_TYPES),"load_snapshot":bounded_load_snapshot(load),"rate_confirmation":({"document_id":rate_doc["id"],"rate_confirmation_number":load.get("rate_con_number",""),"filename":rate_doc.get("filename",""),"document_type":rate_doc.get("doc_type"),"captured_at":now} if rate_doc else None),"broker_snapshot":{"name":load.get("broker","")},"shipper_snapshot":{"name":load.get("customer","") ,"pickup_facility":load.get("pickup_address","")},"profitability_snapshot":calculate_profitability(load,assumptions),"assignment_snapshot":assignment,"checkpoints":checkpoints,"evidence_document_ids":[rate_doc["id"]] if rate_doc else [],"last_material_change_at":None})
        audit=await begin_audit(db.audit_events,user,"load_passport.created",AuditEntityType.LOAD_PASSPORT,pid,changed_fields=["id","load_id","status","version"])
        try: await db.load_passports.insert_one(doc)
        except Exception:
            await audit.rejected("duplicate_load_passport"); raise HTTPException(409,"An active passport already exists for this load")
        await audit.succeeded(doc); return _public(doc)
    @api.put("/load-passports/{passport_id}")
    async def update_passport(passport_id:str,data:PassportUpdate,user=Depends(get_current_user)):
        _role(user,OPERATIONAL_ROLES); p=await _passport(db,user,passport_id); updates=data.model_dump(exclude_unset=True)
        audit=await begin_audit(db.audit_events,user,"load_passport.updated",AuditEntityType.LOAD_PASSPORT,passport_id,changed_fields=list(updates),previous=p)
        if "trailer_identifier" in updates:
            a=dict(p["assignment_snapshot"]); changed=a.get("trailer_identifier")!=updates["trailer_identifier"]; a["trailer_identifier"]=updates.pop("trailer_identifier"); updates["assignment_snapshot"]=a
            if changed:
                cases=await preinvalidate_for_load(db,user,p["load_id"],["trailer"])
                if cases: p=await _passport(db,user,passport_id)
                if p["status"] in {"approved","pickup_authorized"}: updates.update(_invalidated(p,user))
        return await _replace(db,audit,user,p,updates,"passport update")
    @api.put("/load-passports/{passport_id}/checkpoints/{checkpoint_type}")
    async def update_checkpoint(passport_id:str,checkpoint_type:CheckpointType,data:CheckpointUpdate,user=Depends(get_current_user)):
        p=await _passport(db,user,passport_id); role=user.get("role"); kind=checkpoint_type.value
        if role not in ADMIN_ROLES and role not in CHECKPOINT_ROLES[kind]: raise HTTPException(403,"Checkpoint belongs to another operational domain")
        if data.status==CheckpointStatus.WAIVED and role not in ADMIN_ROLES: raise HTTPException(403,"Only owner or admin may waive a checkpoint")
        for evidence_id in data.evidence_document_ids:
            if not await db.documents.find_one(tenant_filter(user,{"id":evidence_id,"load_id":p["load_id"]}),{"_id":0}): raise HTTPException(404,"Not found")
        cps=[dict(c) for c in p["checkpoints"]]; idx=next(i for i,c in enumerate(cps) if c["type"]==kind); now=utc_now(); cps[idx]={"type":kind,**data.model_dump(mode="json"),"checked_at":now,"checked_by":user["id"],"checked_by_role":role}
        all_satisfied=all(c.get("status") in {"pass","waived"} or not c.get("blocking",True) for c in cps)
        cleared={"required_checkpoints_unsatisfied"}
        if all_satisfied: cleared.add("material_change_requires_reapproval")
        reasons=[r for r in p.get("blocking_reasons",[]) if r not in cleared]
        audit=await begin_audit(db.audit_events,user,"load_passport.checkpoint_updated",AuditEntityType.LOAD_PASSPORT,passport_id,changed_fields=["checkpoints","version"],previous=p)
        return await _replace(db,audit,user,p,{"checkpoints":cps,"blocking_reasons":reasons},"checkpoint update")
    @api.post("/load-passports/{passport_id}/refresh-profitability")
    async def refresh_profitability(passport_id:str,data:EmptyAction,user=Depends(get_current_user)):
        _role(user,ADMIN_ROLES|{"finance"}); p=await _passport(db,user,passport_id); load=await _load(db,user,p["load_id"]); a=await db.assumptions.find_one(tenant_filter(user,{"id":"default"}),{"_id":0}) or {}; cps=[dict(c) for c in p["checkpoints"]]
        for cp in cps:
            if cp["type"]=="profitability": cp.update({"status":"pending","checked_at":None,"checked_by":None,"checked_by_role":None,"reason_code":"","notes":"","evidence_document_ids":[],"expires_at":None,"source":"system"})
        audit=await begin_audit(db.audit_events,user,"load_passport.profitability_refreshed",AuditEntityType.LOAD_PASSPORT,passport_id,changed_fields=["profitability_snapshot","checkpoints","version"],previous=p)
        return await _replace(db,audit,user,p,{"profitability_snapshot":calculate_profitability(load,a),"checkpoints":cps},"profitability refresh")
    async def transition(pid,user,target,action,reason=""):
        p=await _passport(db,user,pid)
        if target==p["status"]: return p
        if target not in ALLOWED.get(p["status"],set()): raise HTTPException(409,f"Transition from {p['status']} to {target} is not allowed")
        load=await _load(db,user,p["load_id"]); readiness=evaluate_readiness(p,load); updates={"status":target}
        if target=="review_pending":
            if not readiness["ready_for_review"]: raise HTTPException(409,detail=readiness)
            updates.update({"submitted_at":utc_now(),"submitted_by":user["id"],"blocking_reasons":[]})
        if target=="approved":
            if not readiness["ready_for_approval"]: raise HTTPException(409,detail=readiness)
            updates.update({"approved_at":utc_now(),"approved_by":user["id"],"approved_version":p["version"]+1,"rejection_reason":""})
        if target=="blocked": updates.update({"rejected_at":utc_now(),"rejected_by":user["id"],"rejection_reason":reason,"blocking_reasons":["human_review_blocked"]})
        if target=="revoked": updates.update(_revoked(p,user,reason))
        audit=await begin_audit(db.audit_events,user,action,AuditEntityType.LOAD_PASSPORT,pid,changed_fields=list(updates),previous=p)
        return await _replace(db,audit,user,p,updates,"passport transition")
    @api.post("/load-passports/{passport_id}/submit")
    async def submit(passport_id:str,data:EmptyAction,user=Depends(get_current_user)): _role(user,OPERATIONAL_ROLES); return await transition(passport_id,user,"review_pending","load_passport.submitted")
    @api.post("/load-passports/{passport_id}/approve")
    async def approve(passport_id:str,data:EmptyAction,user=Depends(get_current_user)): _role(user,ADMIN_ROLES); return await transition(passport_id,user,"approved","load_passport.approved")
    @api.post("/load-passports/{passport_id}/reject")
    async def reject(passport_id:str,data:ReasonAction,user=Depends(get_current_user)): _role(user,ADMIN_ROLES); return await transition(passport_id,user,"blocked","load_passport.blocked",data.reason)
    @api.post("/load-passports/{passport_id}/return-to-review")
    async def return_review(passport_id:str,data:EmptyAction,user=Depends(get_current_user)): _role(user,OPERATIONAL_ROLES); return await transition(passport_id,user,"review_pending","load_passport.submitted")
    @api.post("/load-passports/{passport_id}/revoke")
    async def revoke(passport_id:str,data:ReasonAction,user=Depends(get_current_user)): _role(user,ADMIN_ROLES); return await transition(passport_id,user,"revoked","load_passport.revoked",data.reason)
    @api.post("/load-passports/{passport_id}/authorize-pickup")
    async def authorize_pickup(passport_id:str,data:EmptyAction,user=Depends(get_current_user)):
        _role(user,ADMIN_ROLES); p=await _passport(db,user,passport_id); load=await _load(db,user,p["load_id"]); ready=evaluate_readiness(p,load)
        await shadow_evaluate_passport_authorization(db,settings,user,p,load,ready)
        if not ready["ready_for_pickup_authorization"]: raise HTTPException(409,detail=ready)
        authorization={"id":_id("pua_"),"passport_id":p["id"],"passport_version":p["version"]+1,"status":"active","issued_at":utc_now(),"issued_by":user["id"],"revoked_at":None,"revoked_by":None,"revocation_reason":"","load_id":p["load_id"],"driver_id":p["assignment_snapshot"].get("driver_id"),"truck_id":p["assignment_snapshot"].get("truck_id"),"trailer_identifier":p["assignment_snapshot"].get("trailer_identifier",""),"pickup_location":p["load_snapshot"].get("pickup_address",""),"pickup_window":p["load_snapshot"].get("pickup_appt","")}
        authorization["authorization_snapshot_hash"]=canonical_hash({k:v for k,v in authorization.items() if k not in {"id","issued_at","issued_by","revoked_at","revoked_by","revocation_reason","authorization_snapshot_hash"}}|{"checkpoints":p["checkpoints"]})
        audit=await begin_audit(db.audit_events,user,"pickup_authorization.issued",AuditEntityType.PICKUP_AUTHORIZATION,authorization["id"],changed_fields=["status","version"],previous=p)
        return await _replace(db,audit,user,p,{"status":"pickup_authorized","pickup_authorization":authorization},"pickup authorization")
    @api.post("/load-passports/{passport_id}/revoke-pickup")
    async def revoke_pickup(passport_id:str,data:ReasonAction,user=Depends(get_current_user)):
        _role(user,ADMIN_ROLES); p=await _passport(db,user,passport_id)
        if not p.get("pickup_authorization") or p["pickup_authorization"].get("status")!="active": raise HTTPException(409,"No active pickup authorization")
        updates=_revoked(p,user,data.reason); audit=await begin_audit(db.audit_events,user,"pickup_authorization.revoked",AuditEntityType.PICKUP_AUTHORIZATION,p["pickup_authorization"]["id"],changed_fields=list(updates),previous=p)
        return await _replace(db,audit,user,p,updates,"pickup revocation")
def _revoked(p,user,reason):
    auth=dict(p.get("pickup_authorization") or {})
    if auth: auth.update({"status":"revoked","revoked_at":utc_now(),"revoked_by":user["id"],"revocation_reason":reason})
    return {"status":"revoked","pickup_authorization":auth or None,"blocking_reasons":["approval_revoked"]}
def _invalidated(p,user):
    auth=dict(p.get("pickup_authorization") or {})
    if auth and auth.get("status")=="active": auth.update({"status":"revoked","revoked_at":utc_now(),"revoked_by":user["id"],"revocation_reason":"material_change_requires_reapproval"})
    return {"status":"review_pending","approved_at":None,"approved_by":None,"approved_version":None,"pickup_authorization":auth or None,"blocking_reasons":["material_change_requires_reapproval"],"last_material_change_at":utc_now()}
