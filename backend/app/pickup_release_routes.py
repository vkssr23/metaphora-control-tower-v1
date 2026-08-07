import secrets
from fastapi import Depends,HTTPException,Query,status
from app.audit import begin_audit
from app.schemas.audit import AuditEntityType
from app.schemas.pickup_release import CaseCreate,CaseUpdate,EmptyAction,ReasonAction,ChecklistUpdate,ChecklistType,FindingUpdate,EvidenceAdd,DriverAcknowledge,PickupConfirm,ExceptionAction
from app.tenant import tenant_document,tenant_filter,require_tenant_id
from app.domain.pickup_release import EDITABLE,TRANSITIONS,bounded_snapshot,contact_snapshot,evaluate,authorization,authorization_binding,revoke_authorization,utc_now

ADMIN={"owner","admin"}; OPS=ADMIN|{"operations","dispatcher"}; REVIEW=OPS|{"safety","compliance"}
def role(user,allowed):
    require_tenant_id(user)
    if user.get("role") not in allowed: raise HTTPException(403,"Insufficient permission")
def clean(d): d.pop("_id",None); return d
async def one(db,user,cid):
    c=await db.pickup_release_cases.find_one(tenant_filter(user,{"id":cid}),{"_id":0})
    if not c: raise HTTPException(404,"Pickup release case not found")
    return clean(c)
async def guarded(db,user,c,updates,audit):
    updates={**updates,"version":c["version"]+1,"updated_at":utc_now(),"updated_by":user["id"]}
    try:r=await db.pickup_release_cases.update_one(tenant_filter(user,{"id":c["id"],"status":c["status"],"version":c["version"]}),{"$set":updates})
    except Exception: await audit.failed("internal_failure"); raise HTTPException(500,"Database operation failed")
    if not r.matched_count: await audit.rejected("version_conflict"); raise HTTPException(409,"Release case changed concurrently")
    await audit.succeeded({"id":c["id"],"load_id":c["load_id"],"status":updates.get("status",c["status"]),"version":updates["version"]})
    return await one(db,user,c["id"])
async def prereqs(db,user,c):
    load=await db.loads.find_one(tenant_filter(user,{"id":c["load_id"]}),{"_id":0})
    passport=await db.load_passports.find_one(tenant_filter(user,{"id":c["passport_id"]}),{"_id":0})
    rate=await db.rate_confirmation_extractions.find_one(tenant_filter(user,{"id":c.get("rate_confirmation_extraction_id")}),{"_id":0}) if c.get("rate_confirmation_extraction_id") else None
    party=await db.party_verification_cases.find_one(tenant_filter(user,{"id":c.get("party_verification_case_id")}),{"_id":0}) if c.get("party_verification_case_id") else None
    execution=await db.execution_eligibility_cases.find_one(tenant_filter(user,{"id":c.get("execution_eligibility_case_id")}),{"_id":0}) if c.get("execution_eligibility_case_id") else None
    return load,passport,rate,party,execution
def custody(kind,user,at,**extra): return {"id":"cue_"+secrets.token_hex(8),"type":kind,"occurred_at":at,"recorded_by":user["id"],"recorded_by_role":user["role"],"source":"manual" if kind!="authorization_issued" else "system",**extra}
def prerequisite_snapshot(passport,rate,party,execution):
    return {"passport_id":passport.get("id"),"passport_version":passport.get("version"),"rate_confirmation_id":rate.get("id") if rate else None,"rate_confirmation_version":rate.get("version") if rate else None,"rate_confirmation_revision":rate.get("revision") if rate else None,"rate_confirmation_status":rate.get("status") if rate else None,"rate_confirmation_document_id":rate.get("document_id") if rate else None,"party_verification_id":party.get("id") if party else None,"party_verification_version":party.get("version") if party else None,"party_verification_status":party.get("status") if party else None,"execution_eligibility_id":execution.get("id") if execution else None,"execution_eligibility_version":execution.get("version") if execution else None,"execution_eligibility_status":execution.get("status") if execution else None}
def timestamp_result(result,now):
    out={k:v for k,v in result.items() if k!="as_of"}; out["evaluated_at"]=now
    out["checklist_items"]=[{**x,"checked_at":now,"checked_by":None,"checked_by_role":None} for x in result["checklist_items"]]
    out["findings"]=[{**x,"created_at":now,"resolved_at":None,"resolved_by":None,"resolved_by_role":None} for x in result["findings"]]
    return out

def register_pickup_release_routes(api,db,get_current_user):
    @api.get("/pickup-release-cases")
    async def listing(load_id:str|None=None,limit:int=Query(100,ge=1,le=200),user=Depends(get_current_user)):
        return await db.pickup_release_cases.find(tenant_filter(user,{"load_id":load_id} if load_id else {}),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(limit)
    @api.get("/pickup-release-cases/{cid}")
    async def get(cid:str,user=Depends(get_current_user)): return await one(db,user,cid)
    @api.get("/loads/{load_id}/pickup-release-case")
    async def by_load(load_id:str,user=Depends(get_current_user)):
        if not await db.loads.find_one(tenant_filter(user,{"id":load_id}),{"_id":0}): raise HTTPException(404,"Load not found")
        c=await db.pickup_release_cases.find_one(tenant_filter(user,{"load_id":load_id}),{"_id":0})
        if not c: raise HTTPException(404,"Pickup release case not found")
        return clean(c)
    @api.post("/loads/{load_id}/pickup-release-case",status_code=status.HTTP_201_CREATED)
    async def create(load_id:str,data:CaseCreate,user=Depends(get_current_user)):
        role(user,OPS); load=await db.loads.find_one(tenant_filter(user,{"id":load_id}),{"_id":0})
        if not load: raise HTTPException(404,"Load not found")
        prior=await db.pickup_release_cases.find_one(tenant_filter(user,{"load_id":load_id}),{"_id":0})
        if prior and prior.get("status") not in {"expired","revoked"}: raise HTTPException(409,"An active pickup release case already exists")
        passport=await db.load_passports.find_one(tenant_filter(user,{"load_id":load_id}),{"_id":0})
        if not passport: raise HTTPException(404,"Load Passport not found")
        rates=await db.rate_confirmation_extractions.find(tenant_filter(user,{"load_id":load_id,"status":"accepted"}),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(1); parties=await db.party_verification_cases.find(tenant_filter(user,{"load_id":load_id,"status":"cleared"}),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(1); executions=await db.execution_eligibility_cases.find(tenant_filter(user,{"load_id":load_id,"status":"eligible"}),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(1)
        rate=rates[0] if rates else None; party=parties[0] if parties else None; execution=executions[0] if executions else None; now=utc_now(); cid="prc_"+secrets.token_hex(12)
        snap=bounded_snapshot(load,passport,rate or {},party or {},execution or {})
        doc=tenant_document(user,{"id":cid,"load_id":load_id,"passport_id":passport["id"],"execution_eligibility_case_id":execution.get("id") if execution else None,"party_verification_case_id":party.get("id") if party else None,"rate_confirmation_extraction_id":rate.get("id") if rate else None,"version":1,"status":"draft","verdict":"pending","created_at":now,"created_by":user["id"],"updated_at":now,"updated_by":user["id"],"evaluated_at":None,"evaluated_by":None,"submitted_at":None,"submitted_by":None,"released_at":None,"released_by":None,"blocked_at":None,"blocked_by":None,"block_reason":"","revoked_at":None,"revoked_by":None,"revocation_reason":"","pickup_authorization_id":None,"pickup_authorization_version":None,"release_snapshot":snap,"assignment_snapshot":snap["load"],"facility_snapshot":{"name":snap["load"].get("pickup_facility"),"address":snap["load"].get("pickup_address")},"contact_snapshot":contact_snapshot(party),"instruction_snapshot":snap["load"],"prerequisite_snapshot":prerequisite_snapshot(passport,rate,party,execution),"checklist_items":[],"findings":[],"warnings":[],"blocking_reasons":[],"evidence_document_ids":[],"custody_state":"not_authorized","custody_events":[],"current_custody_holder":None,"pickup_confirmed_at":None,"pickup_confirmed_by":None,"last_material_change_at":None,"operational_notes":""})
        a=await begin_audit(db.audit_events,user,"pickup_release.created",AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=["id","load_id","passport_id","status","version"])
        try: await db.pickup_release_cases.insert_one(doc)
        except Exception: await a.failed("internal_failure"); raise HTTPException(500,"Database operation failed")
        await a.succeeded(doc); return clean(doc)
    @api.put("/pickup-release-cases/{cid}")
    async def update(cid:str,data:CaseUpdate,user=Depends(get_current_user)):
        role(user,OPS); c=await one(db,user,cid)
        if c["status"] not in EDITABLE: raise HTTPException(409,"Released or release-ready cases cannot be ordinarily edited")
        u=data.model_dump(exclude_unset=True); a=await begin_audit(db.audit_events,user,"pickup_release.updated",AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=list(u)+["version"],previous=c); return await guarded(db,user,c,u,a)
    async def evaluate_case(cid,user,refresh=False):
        c=await one(db,user,cid)
        if c["status"] in {"released","pickup_confirmed","exception"}: raise HTTPException(409,"Released cases are immutable outside controlled custody actions")
        load,p,r,party,e=await prereqs(db,user,c)
        if not load or not p: raise HTTPException(409,"Required release prerequisite is unavailable")
        updates={}
        if refresh:
            snap=bounded_snapshot(load,p,r or {},party or {},e or {}); updates={"release_snapshot":snap,"assignment_snapshot":snap["load"],"facility_snapshot":{"name":snap["load"].get("pickup_facility"),"address":snap["load"].get("pickup_address")},"contact_snapshot":contact_snapshot(party),"instruction_snapshot":snap["load"],"prerequisite_snapshot":prerequisite_snapshot(p,r,party,e),"verdict":"pending","checklist_items":[],"findings":[],"blocking_reasons":[],"warning_reasons":[]}
            return c,updates
        now=utc_now(); result=evaluate(load,p,r,party,e,c,{"as_of":now}); updates.update(timestamp_result(result,now)); updates["evaluated_by"]=user["id"]
        return c,updates
    @api.post("/pickup-release-cases/{cid}/refresh")
    async def refresh(cid:str,data:EmptyAction,user=Depends(get_current_user)):
        role(user,REVIEW); c,u=await evaluate_case(cid,user,True); a=await begin_audit(db.audit_events,user,"pickup_release.snapshots_refreshed",AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=list(u)+["version"],previous=c); return await guarded(db,user,c,u,a)
    @api.post("/pickup-release-cases/{cid}/evaluate")
    async def eval_route(cid:str,data:EmptyAction,user=Depends(get_current_user)):
        role(user,REVIEW); c,u=await evaluate_case(cid,user); a=await begin_audit(db.audit_events,user,"pickup_release.evaluated",AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=list(u)+["version"],previous=c); return await guarded(db,user,c,u,a)
    async def transition(cid,user,target,action,reason=""):
        c=await one(db,user,cid)
        if target not in TRANSITIONS.get(c["status"],set()): raise HTTPException(409,"Invalid pickup release transition")
        now=utc_now(); u={"status":target,"verdict":"pending" if target=="review_pending" else "blocked" if target=="blocked" else c.get("verdict","pending")}
        if target=="review_pending": u.update({"submitted_at":now,"submitted_by":user["id"]})
        if target=="blocked": u.update({"blocked_at":now,"blocked_by":user["id"],"block_reason":reason})
        a=await begin_audit(db.audit_events,user,action,AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=list(u)+["version"],previous=c); return await guarded(db,user,c,u,a)
    @api.post("/pickup-release-cases/{cid}/submit")
    async def submit(cid:str,data:EmptyAction,user=Depends(get_current_user)): role(user,OPS); return await transition(cid,user,"review_pending","pickup_release.submitted")
    @api.post("/pickup-release-cases/{cid}/release-ready")
    async def ready(cid:str,data:EmptyAction,user=Depends(get_current_user)):
        role(user,ADMIN); c,u=await evaluate_case(cid,user)
        if c["status"] not in {"review_pending","review_required"} or u["verdict"]!="release_ready": raise HTTPException(409,{"verdict":u["verdict"],"blocking_reasons":u["blocking_reasons"],"warning_reasons":u["warning_reasons"]})
        a=await begin_audit(db.audit_events,user,"pickup_release.release_ready",AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=list(u)+["status","version"],previous=c); return await guarded(db,user,c,{**u,"status":"release_ready"},a)
    @api.post("/pickup-release-cases/{cid}/block")
    async def block(cid:str,data:ReasonAction,user=Depends(get_current_user)): role(user,REVIEW); return await transition(cid,user,"blocked","pickup_release.blocked",data.reason)
    @api.post("/pickup-release-cases/{cid}/return-to-review")
    async def rereview(cid:str,data:EmptyAction,user=Depends(get_current_user)): role(user,ADMIN); return await transition(cid,user,"review_pending","pickup_release.returned_to_review")
    @api.put("/pickup-release-cases/{cid}/checklist/{kind}")
    async def checklist(cid:str,kind:ChecklistType,data:ChecklistUpdate,user=Depends(get_current_user)):
        role(user,REVIEW); c=await one(db,user,cid)
        if c["status"] not in EDITABLE: raise HTTPException(409,"Case is immutable")
        if data.result.value=="waived" and user["role"] not in ADMIN: raise HTTPException(403,"Only owner or admin may waive")
        items=[x for x in c.get("checklist_items",[]) if x.get("type")!=kind.value]+[{"type":kind.value,"result":data.result.value,"source":"manual","reason":data.reason,"checked_at":utc_now(),"checked_by":user["id"],"checked_by_role":user["role"]}]
        a=await begin_audit(db.audit_events,user,"pickup_release.checklist_updated",AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=["checklist_items","version"],previous=c); return await guarded(db,user,c,{"checklist_items":items},a)
    @api.put("/pickup-release-cases/{cid}/findings/{fid}")
    async def finding_update(cid:str,fid:str,data:FindingUpdate,user=Depends(get_current_user)):
        role(user,REVIEW); c=await one(db,user,cid)
        if c["status"] not in EDITABLE: raise HTTPException(409,"Case is immutable")
        fs=[dict(x) for x in c.get("findings",[])]; f=next((x for x in fs if x.get("id")==fid),None)
        if not f: raise HTTPException(404,"Finding not found")
        if data.resolution=="waived" and user["role"] not in ADMIN: raise HTTPException(403,"Only owner or admin may waive")
        f.update({"status":"waived" if data.resolution=="waived" else "resolved","resolution":data.resolution,"resolution_reason":data.reason,"resolved_at":utc_now(),"resolved_by":user["id"],"resolved_by_role":user["role"]})
        a=await begin_audit(db.audit_events,user,"pickup_release.finding_resolved",AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=["finding_id","findings","version"],previous=c); return await guarded(db,user,c,{"findings":fs},a)
    @api.post("/pickup-release-cases/{cid}/evidence")
    async def evidence(cid:str,data:EvidenceAdd,user=Depends(get_current_user)):
        role(user,REVIEW); c=await one(db,user,cid)
        if c["status"] not in EDITABLE: raise HTTPException(409,"Case is immutable")
        for did in data.document_ids:
            if not await db.documents.find_one(tenant_filter(user,{"id":did,"load_id":c["load_id"]}),{"_id":0}): raise HTTPException(404,"Evidence document not found")
        ids=sorted(set(c.get("evidence_document_ids",[]))|set(data.document_ids)); a=await begin_audit(db.audit_events,user,"pickup_release.evidence_added",AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=["evidence_document_ids","version"],previous=c); return await guarded(db,user,c,{"evidence_document_ids":ids},a)
    @api.post("/pickup-release-cases/{cid}/release")
    async def release(cid:str,data:EmptyAction,user=Depends(get_current_user)):
        role(user,ADMIN); observed=await one(db,user,cid)
        if observed["status"]!="release_ready": raise HTTPException(409,"Case must be release_ready")
        a=await begin_audit(db.audit_events,user,"pickup_release.released",AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=["status","version","pickup_authorization_id","custody_state"],previous=observed)
        load,p,r,party,e=await prereqs(db,user,observed); now=utc_now(); result=timestamp_result(evaluate(load,p,r,party,e,observed,{"as_of":now}),now)
        if result["verdict"]!="release_ready": await a.rejected("release_requirements_unsatisfied"); raise HTTPException(409,result)
        auth=authorization(observed,p,user,now)
        try: pr=await db.load_passports.update_one(tenant_filter(user,{"id":p["id"],"version":p["version"],"status":p["status"]}),{"$set":{"pickup_authorization":auth,"status":"pickup_authorized","version":p["version"]+1,"updated_at":now,"updated_by":user["id"]}})
        except Exception: await a.failed("passport_update_failed"); raise HTTPException(500,"Database operation failed")
        if not pr.matched_count: await a.rejected("passport_version_conflict"); raise HTTPException(409,"Passport changed concurrently")
        event=custody("authorization_issued",user,now,authorization_id=auth["authorization_id"]); final={**result,"status":"released","released_at":now,"released_by":user["id"],"pickup_authorization_id":auth["authorization_id"],"pickup_authorization_version":p["version"]+1,"custody_state":"authorized","custody_events":observed.get("custody_events",[])+[event]}
        try: cr=await db.pickup_release_cases.update_one(tenant_filter(user,{"id":cid,"status":"release_ready","version":observed["version"]}),{"$set":{**final,"version":observed["version"]+1,"updated_at":now,"updated_by":user["id"]}})
        except Exception: cr=None
        if not cr or not cr.matched_count:
            cleanup_at=utc_now(); revoked=revoke_authorization(auth,user,"release_case_finalization_conflict",cleanup_at); rr=await db.load_passports.update_one(tenant_filter(user,{"id":p["id"],"version":p["version"]+1,"pickup_authorization.authorization_id":auth["authorization_id"],"pickup_authorization.status":"active"}),{"$set":{"pickup_authorization":revoked,"status":"review_pending","version":p["version"]+2,"updated_at":cleanup_at,"updated_by":user["id"]}})
            if rr.matched_count: await a.rejected("release_case_version_conflict"); raise HTTPException(409,"Release case changed concurrently; authorization revocation confirmed")
            current=await db.load_passports.find_one(tenant_filter(user,{"id":p["id"]}),{"_id":0}); current_auth=(current or {}).get("pickup_authorization") or {}
            safe=current_auth.get("authorization_id")==auth["authorization_id"] and current_auth.get("status") in {"revoked","expired","consumed"}
            if safe: await a.rejected("release_case_version_conflict"); raise HTTPException(409,"Release case changed concurrently; authorization is not active")
            await a.failed("authorization_cleanup_required"); raise HTTPException(503,"Release finalization conflict requires reconciliation")
        await a.succeeded({"id":cid,"load_id":observed["load_id"],"status":"released","version":observed["version"]+1,"pickup_authorization_id":auth["authorization_id"]}); return await one(db,user,cid)
    @api.post("/pickup-release-cases/{cid}/driver-acknowledge")
    async def acknowledge(cid:str,data:DriverAcknowledge,user=Depends(get_current_user)):
        role(user,REVIEW); c=await one(db,user,cid)
        if c["status"]!="released" or c["custody_state"] not in {"authorized","driver_acknowledged"}: raise HTTPException(409,"Active release authorization required")
        now=utc_now(); events=c.get("custody_events",[])+[custody("driver_acknowledged",user,now)]; a=await begin_audit(db.audit_events,user,"pickup_release.driver_acknowledged",AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=["custody_state","custody_events","version"],previous=c); return await guarded(db,user,c,{"custody_state":"driver_acknowledged","custody_events":events},a)
    @api.post("/pickup-release-cases/{cid}/confirm-pickup")
    async def confirm(cid:str,data:PickupConfirm,user=Depends(get_current_user)):
        role(user,OPS); c=await one(db,user,cid)
        if c["status"]!="released" or c["custody_state"] not in {"authorized","driver_acknowledged"}: raise HTTPException(409,"Active release authorization required")
        load,p,_,_,_=await prereqs(db,user,c); binding=authorization_binding(c,p,load,require_tenant_id(user))
        if not binding["valid"]: raise HTTPException(409,binding["reason"])
        now=utc_now(); auth=dict(p["pickup_authorization"]); auth.update({"state":"consumed","status":"consumed","consumed_at":now,"consumed_by":user["id"]})
        a=await begin_audit(db.audit_events,user,"pickup_release.pickup_confirmed",AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=["status","custody_state","custody_events","version"],previous=c)
        pr=await db.load_passports.update_one(tenant_filter(user,{"id":p["id"],"version":p["version"],"pickup_authorization.authorization_id":auth["authorization_id"],"pickup_authorization.status":"active"}),{"$set":{"pickup_authorization":auth,"version":p["version"]+1,"updated_at":now,"updated_by":user["id"]}})
        if not pr.matched_count: await a.rejected("pickup_authorization_binding_mismatch"); raise HTTPException(409,"pickup_authorization_binding_mismatch")
        events=c.get("custody_events",[])+[custody("pickup_confirmed",user,now,reference=data.reference)]; return await guarded(db,user,c,{"status":"pickup_confirmed","custody_state":"pickup_confirmed","pickup_confirmed_at":now,"pickup_confirmed_by":user["id"],"current_custody_holder":"carrier","custody_events":events},a)
    async def revoke_flow(cid,user,reason,target,action,event_type):
        c=await one(db,user,cid)
        if target not in TRANSITIONS.get(c["status"],set()): raise HTTPException(409,"Invalid pickup release transition")
        _,p,_,_,_=await prereqs(db,user,c); auth=(p or {}).get("pickup_authorization") or {}; now=utc_now(); a=await begin_audit(db.audit_events,user,action,AuditEntityType.PICKUP_RELEASE_CASE,cid,changed_fields=["status","custody_state","custody_events","version"],previous=c)
        if auth.get("status")=="active":
            revoked=revoke_authorization(auth,user,reason,now); pr=await db.load_passports.update_one(tenant_filter(user,{"id":p["id"],"version":p["version"],"pickup_authorization.status":"active"}),{"$set":{"pickup_authorization":revoked,"status":"review_pending","version":p["version"]+1,"updated_at":now,"updated_by":user["id"]}})
            if not pr.matched_count: await a.rejected("passport_version_conflict"); raise HTTPException(409,"Passport changed concurrently")
        events=c.get("custody_events",[])+[custody(event_type,user,now,reason=reason)]; return await guarded(db,user,c,{"status":target,"verdict":"pending" if target=="revoked" else "blocked","custody_state":"exception" if target=="exception" else "revoked","custody_events":events,"revoked_at":now,"revoked_by":user["id"],"revocation_reason":reason},a)
    @api.post("/pickup-release-cases/{cid}/revoke")
    async def revoke(cid:str,data:ReasonAction,user=Depends(get_current_user)): role(user,ADMIN); return await revoke_flow(cid,user,data.reason,"revoked","pickup_release.revoked","authorization_revoked")
    @api.post("/pickup-release-cases/{cid}/exception")
    async def exception(cid:str,data:ExceptionAction,user=Depends(get_current_user)): role(user,OPS); return await revoke_flow(cid,user,data.reason,"exception","pickup_release.exception_opened","exception_opened")
