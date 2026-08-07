import secrets
from fastapi import Depends, HTTPException, Query, status
from app.audit import begin_audit
from app.schemas.audit import AuditEntityType
from app.schemas.execution_eligibility import CaseCreate,CaseUpdate,ManualCheckUpdate,HosUpdate,EvidenceAdd,EmptyAction,ReasonAction,CheckType,FindingUpdate
from app.tenant import tenant_document,tenant_filter,require_tenant_id
from app.domain.execution_eligibility import REQUIRED_CHECK_TYPES,EDITABLE_STATUSES,REFRESH_STATUSES,FINDING_MUTATION_STATUSES,TRANSITIONS,evaluate,passport_sync,utc_now
from app.pickup_release_invalidation import preinvalidate_pickup_release

ADMIN={"owner","admin"}; OPS={"owner","admin","operations","dispatcher"}; SAFETY={"owner","admin","safety","compliance"}
SAFETY_CHECKS={"driver_operational_status","cdl_administrative_status","medical_card_administrative_status","mvr_administrative_status","clearinghouse_administrative_status","employment_verification_status","truck_operational_status","truck_maintenance_condition","truck_insurance_evidence","truck_equipment_compatibility","trailer_equipment_compatibility","load_weight_fit","commodity_equipment_fit"}
def role(user,allowed):
    require_tenant_id(user)
    if user.get("role") not in allowed: raise HTTPException(403,"Insufficient permission")
def public(doc): return {k:v for k,v in doc.items() if k!="_id"}
async def one(db,user,cid):
    c=await db.execution_eligibility_cases.find_one(tenant_filter(user,{"id":cid}),{"_id":0})
    if not c: raise HTTPException(404,"Execution eligibility case not found")
    c.pop("_id",None)
    return c
async def replace(db,user,c,updates,audit,operation):
    updates={**updates,"version":c["version"]+1,"updated_at":utc_now(),"updated_by":user["id"]}
    try:r=await db.execution_eligibility_cases.update_one(tenant_filter(user,{"id":c["id"],"status":c["status"],"version":c["version"]}),{"$set":updates})
    except Exception: await audit.failed(); raise HTTPException(500,"Database operation failed")
    if not r.matched_count: await audit.rejected("version_conflict"); raise HTTPException(409,"Case changed concurrently")
    await audit.succeeded({"id":c["id"],"status":updates.get("status",c["status"]),"version":updates["version"]})
    return await one(db,user,c["id"])
def register_execution_eligibility_routes(api,db,get_current_user):
    @api.get("/execution-eligibility-cases")
    async def listing(load_id:str|None=None,limit:int=Query(100,ge=1,le=200),user=Depends(get_current_user)):
        q=tenant_filter(user,{"load_id":load_id} if load_id else {}); return await db.execution_eligibility_cases.find(q,{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(limit)
    @api.get("/execution-eligibility-cases/{cid}")
    async def get(cid:str,user=Depends(get_current_user)): return await one(db,user,cid)
    @api.post("/loads/{load_id}/execution-eligibility-case",status_code=status.HTTP_201_CREATED)
    async def create(load_id:str,data:CaseCreate,user=Depends(get_current_user)):
        role(user,OPS); load=await db.loads.find_one(tenant_filter(user,{"id":load_id}),{"_id":0})
        if not load: raise HTTPException(404,"Load not found")
        passport=await db.load_passports.find_one(tenant_filter(user,{"load_id":load_id}),{"_id":0})
        if not passport: raise HTTPException(404,"Load Passport not found")
        existing=await db.execution_eligibility_cases.find_one(tenant_filter(user,{"load_id":load_id}),{"_id":0})
        if existing: raise HTTPException(409,"An execution eligibility case already exists for this load")
        for collection,key,label in ((db.drivers,"driver_id","driver"),(db.trucks,"truck_id","truck")):
            if load.get(key) and not await collection.find_one(tenant_filter(user,{"id":load[key]}),{"_id":0}): raise HTTPException(404,f"Assigned {label} not found")
        now=utc_now(); cid="eec_"+secrets.token_hex(8)
        doc=tenant_document(user,{"id":cid,"load_id":load_id,"passport_id":passport["id"],"version":1,"status":"draft","verdict":"pending","created_at":now,"created_by":user["id"],"updated_at":now,"updated_by":user["id"],"evaluated_at":None,"evaluated_by":None,"submitted_at":None,"submitted_by":None,"approved_at":None,"approved_by":None,"blocked_at":None,"blocked_by":None,"block_reason":"","revoked_at":None,"revoked_by":None,"revocation_reason":"","expires_at":None,"driver_snapshot":{},"truck_snapshot":{},"trailer_snapshot":{"identifier":data.trailer_identifier,"declared_equipment_type":data.trailer_equipment_type,"source":"manual","reviewed_at":now,"reviewed_by":user["id"]},"load_fit_snapshot":{},"compliance_snapshot":{},"appointment_snapshot":{},"hos_readiness_snapshot":{},"checks":[],"findings":[],"blocking_reasons":[],"warning_reasons":[],"required_check_types":list(REQUIRED_CHECK_TYPES),"evidence_document_ids":[],"passport_version":passport["version"],"party_verification_case_id":None,"party_verification_case_version":None,"last_material_change_at":None,"operational_notes":""})
        audit=await begin_audit(db.audit_events,user,"execution_eligibility.created",AuditEntityType.EXECUTION_ELIGIBILITY_CASE,cid,changed_fields=["id","load_id","passport_id","status","version"])
        try: await db.execution_eligibility_cases.insert_one(doc)
        except Exception: await audit.failed(); raise HTTPException(500,"Database operation failed")
        await audit.succeeded(doc); return public(doc)
    @api.put("/execution-eligibility-cases/{cid}")
    async def update(cid:str,data:CaseUpdate,user=Depends(get_current_user)):
        role(user,OPS); c=await one(db,user,cid)
        if c["status"] not in EDITABLE_STATUSES: raise HTTPException(409,"Eligible cases cannot be ordinarily edited")
        raw=data.model_dump(exclude_unset=True); trailer=dict(c.get("trailer_snapshot",{}))
        if "trailer_identifier" in raw: trailer["identifier"]=raw.pop("trailer_identifier")
        if "trailer_equipment_type" in raw: trailer["declared_equipment_type"]=raw.pop("trailer_equipment_type")
        if trailer!=c.get("trailer_snapshot",{}): trailer.update({"source":"manual","reviewed_at":utc_now(),"reviewed_by":user["id"]}); raw["trailer_snapshot"]=trailer
        a=await begin_audit(db.audit_events,user,"execution_eligibility.updated",AuditEntityType.EXECUTION_ELIGIBILITY_CASE,cid,changed_fields=list(raw),previous=c)
        return await replace(db,user,c,raw,a,"case update")
    @api.put("/execution-eligibility-cases/{cid}/checks/{kind}")
    async def check(cid:str,kind:CheckType,data:ManualCheckUpdate,user=Depends(get_current_user)):
        c=await one(db,user,cid); k=kind.value; role(user,SAFETY if k in SAFETY_CHECKS else OPS)
        if c["status"] not in EDITABLE_STATUSES: raise HTTPException(409,"Eligible cases cannot be ordinarily edited")
        if data.result.value=="waived" and user.get("role") not in ADMIN: raise HTTPException(403,"Only owner or admin may waive a check")
        if data.result.value=="waived" and k in {"driver_assignment","truck_assignment","required_party_clearance","required_rate_confirmation","required_load_passport_state"}: raise HTTPException(409,"This prerequisite cannot be waived")
        checks=[x for x in c.get("checks",[]) if x.get("type")!=k]+[{"type":k,"result":data.result.value,"source":"manual","reason":data.reason,"checked_at":utc_now(),"checked_by":user["id"],"checked_by_role":user["role"]}]
        a=await begin_audit(db.audit_events,user,"execution_eligibility.check_updated",AuditEntityType.EXECUTION_ELIGIBILITY_CASE,cid,changed_fields=["checks","version"],previous=c)
        return await replace(db,user,c,{"checks":checks},a,"check update")
    @api.put("/execution-eligibility-cases/{cid}/hos")
    @api.put("/execution-eligibility-cases/{cid}/hos-readiness")
    async def hos(cid:str,data:HosUpdate,user=Depends(get_current_user)):
        role(user,OPS|SAFETY); c=await one(db,user,cid)
        if c["status"] not in EDITABLE_STATUSES: raise HTTPException(409,"Eligible cases cannot be ordinarily edited")
        snap={**data.model_dump(),"reviewed_at":utc_now(),"reviewed_by":user["id"],"limitation":"internal planning evidence; not ELD verification"}
        a=await begin_audit(db.audit_events,user,"execution_eligibility.hos_updated",AuditEntityType.EXECUTION_ELIGIBILITY_CASE,cid,changed_fields=["hos_readiness_snapshot","version"],previous=c)
        return await replace(db,user,c,{"hos_readiness_snapshot":snap},a,"HOS update")
    @api.post("/execution-eligibility-cases/{cid}/evidence")
    async def evidence(cid:str,data:EvidenceAdd,user=Depends(get_current_user)):
        role(user,OPS|SAFETY); c=await one(db,user,cid)
        if c["status"] not in EDITABLE_STATUSES: raise HTTPException(409,"Eligible cases cannot be ordinarily edited")
        for did in data.document_ids:
            if not await db.documents.find_one(tenant_filter(user,{"id":did,"load_id":c["load_id"]}),{"_id":0}): raise HTTPException(404,"Evidence document not found")
        ids=sorted(set(c.get("evidence_document_ids",[]))|set(data.document_ids)); a=await begin_audit(db.audit_events,user,"execution_eligibility.evidence_added",AuditEntityType.EXECUTION_ELIGIBILITY_CASE,cid,changed_fields=["evidence_document_ids","version"],previous=c)
        return await replace(db,user,c,{"evidence_document_ids":ids},a,"evidence update")
    async def evaluated(cid,user):
        c=await one(db,user,cid)
        if c["status"] not in {"draft","review_pending","review_required","blocked","expired","revoked"}: raise HTTPException(409,"Case cannot be evaluated in current status")
        load=await db.loads.find_one(tenant_filter(user,{"id":c["load_id"]}),{"_id":0}); passport=await db.load_passports.find_one(tenant_filter(user,{"id":c["passport_id"]}),{"_id":0})
        if not load or not passport: raise HTTPException(404,"Eligibility prerequisite not found")
        driver=await db.drivers.find_one(tenant_filter(user,{"id":load.get("driver_id")}),{"_id":0}) if load.get("driver_id") else None; truck=await db.trucks.find_one(tenant_filter(user,{"id":load.get("truck_id")}),{"_id":0}) if load.get("truck_id") else None
        parties=await db.party_verification_cases.find(tenant_filter(user,{"load_id":c["load_id"]}),{"_id":0}).sort("updated_at",-1).to_list(1); rates=await db.rate_confirmation_extractions.find(tenant_filter(user,{"load_id":c["load_id"]}),{"_id":0}).sort("updated_at",-1).to_list(1)
        party=parties[0] if parties else None; rate=rates[0] if rates else None; result=evaluate(load,driver,truck,c,passport,party,rate)
        return c,passport,result,{"driver_snapshot":({k:driver.get(k) for k in ("id","name","status","cdl_expiry","medical_expiry","mvr_status","clearinghouse_status","employment_verification") } if driver else {}),"truck_snapshot":({k:truck.get(k) for k in ("id","truck_number","vin","year","status","maintenance_status","insurance_expiry","registration_expiry","annual_inspection_expiry","samsara_id")} if truck else {}),"appointment_snapshot":{"pickup_appt":load.get("pickup_appt"),"delivery_appt":load.get("delivery_appt"),"source":"system"},**result,"evaluated_at":utc_now(),"evaluated_by":user["id"],"party_verification_case_id":party.get("id") if party else None,"party_verification_case_version":party.get("version") if party else None}
    @api.post("/execution-eligibility-cases/{cid}/refresh")
    async def refresh(cid:str,data:EmptyAction,user=Depends(get_current_user)):
        role(user,OPS|SAFETY); current=await one(db,user,cid)
        if current["status"] not in REFRESH_STATUSES: raise HTTPException(409,"Case status does not allow snapshot refresh")
        a=await begin_audit(db.audit_events,user,"execution_eligibility.snapshots_refreshed",AuditEntityType.EXECUTION_ELIGIBILITY_CASE,cid,changed_fields=["driver_snapshot","truck_snapshot","appointment_snapshot","checks","findings","version"],previous=current)
        c,p,result,updates=await evaluated(cid,user)
        updates.pop("verdict",None)
        return await replace(db,user,c,updates,a,"snapshot refresh")
    @api.put("/execution-eligibility-cases/{cid}/findings/{fid}")
    async def finding(cid:str,fid:str,data:FindingUpdate,user=Depends(get_current_user)):
        c=await one(db,user,cid)
        if c["status"] not in FINDING_MUTATION_STATUSES: raise HTTPException(409,"Case status does not allow finding resolution")
        findings=[dict(x) for x in c.get("findings",[])]; target=next((x for x in findings if x.get("id")==fid),None)
        if not target: raise HTTPException(404,"Finding not found")
        role(user,SAFETY if target.get("type") in SAFETY_CHECKS else OPS)
        if data.resolution.value=="waived":
            if user.get("role") not in ADMIN: raise HTTPException(403,"Only owner or admin may waive a finding")
            if target.get("type") in {"driver_assignment","truck_assignment","required_party_clearance","required_rate_confirmation","required_load_passport_state"}: raise HTTPException(409,"Mandatory finding cannot be waived")
        for did in data.evidence_document_ids:
            if not await db.documents.find_one(tenant_filter(user,{"id":did,"load_id":c["load_id"]}),{"_id":0}): raise HTTPException(404,"Evidence document not found")
        target.update({"status":"waived" if data.resolution.value=="waived" else "resolved","resolution":data.resolution.value,"resolution_reason":data.reason,"evidence_document_ids":data.evidence_document_ids,"resolved_at":utc_now(),"resolved_by":user["id"],"resolved_by_role":user["role"]})
        a=await begin_audit(db.audit_events,user,"execution_eligibility.finding_resolved",AuditEntityType.EXECUTION_ELIGIBILITY_CASE,cid,changed_fields=["findings","version"],previous=c)
        return await replace(db,user,c,{"findings":findings},a,"finding resolution")
    @api.post("/execution-eligibility-cases/{cid}/evaluate")
    async def evaluate_route(cid:str,data:EmptyAction,user=Depends(get_current_user)):
        role(user,OPS|SAFETY); c,p,result,updates=await evaluated(cid,user); a=await begin_audit(db.audit_events,user,"execution_eligibility.evaluated",AuditEntityType.EXECUTION_ELIGIBILITY_CASE,cid,changed_fields=list(updates)+["version"],previous=c); return await replace(db,user,c,updates,a,"evaluation")
    async def transition(cid,user,target,action,reason=""):
        c=await one(db,user,cid)
        if target not in TRANSITIONS.get(c["status"],set()): raise HTTPException(409,"Invalid execution eligibility transition")
        updates={"status":target,"verdict":"pending" if target=="review_pending" else "review_required" if target=="review_required" else "blocked" if target=="blocked" else c.get("verdict","pending")}
        ts=utc_now()
        if target=="review_pending": updates.update({"submitted_at":ts,"submitted_by":user["id"]})
        if target=="blocked": updates.update({"blocked_at":ts,"blocked_by":user["id"],"block_reason":reason})
        if target=="revoked": updates.update({"revoked_at":ts,"revoked_by":user["id"],"revocation_reason":reason})
        a=await begin_audit(db.audit_events,user,action,AuditEntityType.EXECUTION_ELIGIBILITY_CASE,cid,changed_fields=list(updates)+["version"],previous=c)
        if c["status"]=="eligible" and target in {"blocked","expired","revoked"}:
            await preinvalidate_pickup_release(db,user,c["load_id"],["execution_eligibility"])
            passport=await db.load_passports.find_one(tenant_filter(user,{"id":c["passport_id"]}),{"_id":0})
            if not passport: await a.rejected("passport_not_found"); raise HTTPException(409,"Execution eligibility passport is unavailable")
            pupdate=passport_sync(passport,c,False,user["id"])
            try: pr=await db.load_passports.update_one(tenant_filter(user,{"id":passport["id"],"version":passport["version"]}),{"$set":pupdate})
            except Exception: await a.failed(); raise HTTPException(500,"Database operation failed")
            if not pr.matched_count: await a.rejected("passport_version_conflict"); raise HTTPException(409,"Passport changed concurrently")
            updates["passport_version"]=pupdate["version"]
        return await replace(db,user,c,updates,a,"transition")
    @api.post("/execution-eligibility-cases/{cid}/submit")
    async def submit(cid:str,data:EmptyAction,user=Depends(get_current_user)): role(user,OPS); return await transition(cid,user,"review_pending","execution_eligibility.submitted")
    @api.post("/execution-eligibility-cases/{cid}/review-required")
    async def review_required(cid:str,data:EmptyAction,user=Depends(get_current_user)): role(user,SAFETY); return await transition(cid,user,"review_required","execution_eligibility.review_required")
    @api.post("/execution-eligibility-cases/{cid}/block")
    async def block(cid:str,data:ReasonAction,user=Depends(get_current_user)): role(user,SAFETY|ADMIN); return await transition(cid,user,"blocked","execution_eligibility.blocked",data.reason)
    @api.post("/execution-eligibility-cases/{cid}/return-to-review")
    async def rereview(cid:str,data:EmptyAction,user=Depends(get_current_user)): role(user,ADMIN); return await transition(cid,user,"review_pending","execution_eligibility.returned_to_review")
    @api.post("/execution-eligibility-cases/{cid}/expire")
    async def expire(cid:str,data:EmptyAction,user=Depends(get_current_user)): role(user,ADMIN); return await transition(cid,user,"expired","execution_eligibility.expired")
    @api.post("/execution-eligibility-cases/{cid}/revoke")
    async def revoke(cid:str,data:ReasonAction,user=Depends(get_current_user)):
        role(user,ADMIN); out=await transition(cid,user,"revoked","execution_eligibility.revoked",data.reason); return out
    @api.post("/execution-eligibility-cases/{cid}/eligible")
    async def eligible(cid:str,data:EmptyAction,user=Depends(get_current_user)):
        role(user,ADMIN); observed=await one(db,user,cid)
        if observed["status"] not in {"review_pending","review_required"}: raise HTTPException(409,"Case must be submitted before eligibility")
        a=await begin_audit(db.audit_events,user,"execution_eligibility.marked_eligible",AuditEntityType.EXECUTION_ELIGIBILITY_CASE,cid,changed_fields=["status","verdict","version","passport_version"],previous=observed)
        c,passport,result,updates=await evaluated(cid,user)
        if c["status"] not in {"review_pending","review_required"}: raise HTTPException(409,"Case must be submitted before eligibility")
        if result["verdict"]!="eligible": await a.rejected("eligibility_requirements_unsatisfied"); raise HTTPException(409,{"verdict":result["verdict"],"blocking_reasons":result["blocking_reasons"],"warning_reasons":result["warning_reasons"]})
        if passport["version"]!=c["passport_version"]: await a.rejected("passport_version_changed"); raise HTTPException(409,"Passport version changed")
        pupdate=passport_sync(passport,c,True,user["id"])
        try: pr=await db.load_passports.update_one(tenant_filter(user,{"id":passport["id"],"version":passport["version"]}),{"$set":pupdate})
        except Exception: await a.failed(); raise HTTPException(500,"Database operation failed")
        if not pr.matched_count: await a.rejected("passport_version_conflict"); raise HTTPException(409,"Passport changed concurrently")
        final={**updates,"status":"eligible","verdict":"eligible","approved_at":utc_now(),"approved_by":user["id"],"passport_version":pupdate["version"],"blocking_reasons":[],"warning_reasons":[]}
        return await replace(db,user,c,final,a,"final eligibility")
