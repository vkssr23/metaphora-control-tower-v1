"""Tenant-scoped, audit-first Phase 1C party-verification workflow."""
import uuid
from fastapi import Depends, HTTPException, Query
from app.audit import begin_audit
from app.schemas.audit import AuditEntityType
from app.tenant import tenant_filter, tenant_document
from app.domain.party_verification import DOMAINS, now, snapshots, evaluate, assert_mutable, qualified_insurance_documents, rate_confirmation_required
from app.schemas.party_verification import CaseCreate,CaseUpdate,EmptyAction,ReasonAction,ReviewUpdate,FindingUpdate,EvidenceAdd,ReviewDomain,ReviewResult,FindingResolution
from app.execution_invalidation import preinvalidate_for_load

ADMIN={"owner","admin"}; OPS=ADMIN|{"operations","dispatcher"}; DOMAIN_ROLES={"broker_identity":OPS,"shipper_identity":OPS,"contact_validation":OPS|{"finance"},"pickup_instructions":OPS,"carrier_authority":ADMIN|{"safety","compliance"},"insurance_evidence":ADMIN|{"safety","compliance","finance"},"fraud_risk":ADMIN|{"safety","compliance","finance"}}
ALLOWED={"draft":{"review_pending"},"review_pending":{"findings_open","cleared","blocked"},"findings_open":{"review_pending","cleared","blocked"},"blocked":{"review_pending"},"cleared":{"expired","revoked"},"expired":{"review_pending"},"revoked":{"review_pending"}}
def role(user,allowed):
    if user.get("role") not in allowed: raise HTTPException(403,"Insufficient permission")
def mutable(c,operation):
    if not assert_mutable(c.get("status"),operation): raise HTTPException(409,f"Case status does not allow {operation}")
async def one(db,user,cid):
    x=await db.party_verification_cases.find_one(tenant_filter(user,{"id":cid}),{"_id":0})
    if not x: raise HTTPException(404,"Not found")
    x.pop("_id",None)
    return x
async def related(db,user,lid):
    load=await db.loads.find_one(tenant_filter(user,{"id":lid}),{"_id":0})
    if not load: raise HTTPException(404,"Not found")
    passport=await db.load_passports.find_one(tenant_filter(user,{"load_id":lid}),{"_id":0})
    if not passport: raise HTTPException(404,"Load Passport not found")
    docs=await db.documents.find(tenant_filter(user,{"load_id":lid}),{"_id":0}).sort([("uploaded_at",-1),("id",-1)]).to_list(100)
    rate_doc_ids={d["id"] for d in docs if d.get("doc_type")=="rate_con"}
    rates=await db.rate_confirmation_extractions.find(tenant_filter(user,{"load_id":lid,"status":"accepted"}),{"_id":0}).sort([("accepted_at",-1),("id",-1)]).to_list(100)
    accepted=next((r for r in rates if r.get("document_id") in rate_doc_ids),None)
    tenant=await db.tenants.find_one({"id":user["tenant_id"]},{"_id":0}) or {}
    return load,passport,accepted,docs,tenant
async def replace(db,audit,user,c,updates):
    updates={**updates,"updated_at":now(),"updated_by":user["id"],"version":c["version"]+1}
    try:r=await db.party_verification_cases.update_one(tenant_filter(user,{"id":c["id"],"status":c["status"],"version":c["version"]}),{"$set":updates})
    except Exception: await audit.failed(); raise HTTPException(500,"Database operation failed")
    if not r.matched_count: await audit.rejected("version_conflict"); raise HTTPException(409,"Verification case changed concurrently")
    await audit.succeeded({"id":c["id"],"load_id":c["load_id"],"version":updates["version"],"status":updates.get("status",c["status"])})
    return await one(db,user,c["id"])
async def evidence(db,user,load_id,ids):
    out=[]
    for did in ids:
        d=await db.documents.find_one(tenant_filter(user,{"id":did}),{"_id":0})
        if not d: raise HTTPException(404,"Not found")
        if d.get("load_id")!=load_id: raise HTTPException(404,"Not found")
        out.append(d)
    return out
def register_party_verification_routes(api,db,get_current_user):
    async def sync_passport(user,c,passed):
        p=await db.load_passports.find_one(tenant_filter(user,{"id":c["passport_id"],"load_id":c["load_id"]}),{"_id":0})
        if not p: raise HTTPException(404,"Load Passport not found")
        cps=[dict(x) for x in p.get("checkpoints",[])]; ts=now()
        for cp in cps:
            if cp.get("type") in {"broker_identity","shipper_identity","pickup_instructions"}:
                cp.update({"status":"pass" if passed else "pending","checked_at":ts if passed else None,"checked_by":user["id"] if passed else None,"checked_by_role":user["role"] if passed else None,"source":"system","notes":"Cleared for internal workflow" if passed else "Party verification requires review","reason_code":"" if passed else "party_verification_requires_review","evidence_document_ids":c.get("evidence_document_ids",[]) if passed else []})
        updates={"checkpoints":cps,"version":p["version"]+1,"updated_at":ts,"updated_by":user["id"]}; auth=dict(p.get("pickup_authorization") or {})
        if not passed:
            updates["status"]="review_pending"; updates["approved_at"]=None; updates["approved_by"]=None; updates["approved_version"]=None
            updates["blocking_reasons"]=sorted(set(p.get("blocking_reasons",[]))|{"party_verification_requires_review"})
            if auth.get("status")=="active": auth.update({"status":"revoked","revoked_at":ts,"revoked_by":user["id"],"revocation_reason":"party_verification_requires_review"}); updates["pickup_authorization"]=auth
        audit=await begin_audit(db.audit_events,user,"party_verification.passport_synchronized",AuditEntityType.LOAD_PASSPORT,p["id"],changed_fields=["status","version"],previous=p)
        try:r=await db.load_passports.update_one(tenant_filter(user,{"id":p["id"],"status":p["status"],"version":p["version"]}),{"$set":updates})
        except Exception: await audit.failed(); raise HTTPException(500,"Database operation failed")
        if not r.matched_count: await audit.rejected("version_conflict"); raise HTTPException(409,"Load Passport changed concurrently")
        await audit.succeeded({"id":p["id"],"load_id":p["load_id"],"status":updates.get("status",p["status"]),"version":updates["version"]})
        return updates["version"]
    @api.get("/party-verification-cases")
    async def list_cases(limit:int=Query(100,ge=1,le=200),user=Depends(get_current_user)):
        rows=await db.party_verification_cases.find(tenant_filter(user),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(limit)
        for row in rows: row.pop("_id",None)
        return rows
    @api.get("/party-verification-cases/{cid}")
    async def get_case(cid:str,user=Depends(get_current_user)): return await one(db,user,cid)
    @api.get("/loads/{lid}/party-verification-case")
    async def get_load_case(lid:str,user=Depends(get_current_user)):
        if not await db.loads.find_one(tenant_filter(user,{"id":lid}),{"_id":0}): raise HTTPException(404,"Not found")
        x=await db.party_verification_cases.find_one(tenant_filter(user,{"load_id":lid}),{"_id":0})
        if not x: raise HTTPException(404,"Not found")
        x.pop("_id",None)
        return x
    @api.post("/loads/{lid}/party-verification-case",status_code=201)
    async def create(lid:str,data:CaseCreate,user=Depends(get_current_user)):
        role(user,OPS); load,p,rate,docs,tenant=await related(db,user,lid)
        if await db.party_verification_cases.find_one(tenant_filter(user,{"load_id":lid}),{"_id":0}): raise HTTPException(409,"A verification case already exists for this load")
        b,s,c,i,cv,pi=snapshots(load,p,rate,docs,tenant); cid=f"pvc_{uuid.uuid4().hex}"; ts=now(); reviews={d:{"domain":d,"result":"pending","source":"system","reason":"","evidence_document_ids":[],"reviewed_at":None,"reviewed_by":None,"reviewed_by_role":None} for d in DOMAINS}
        doc=tenant_document(user,{"id":cid,"load_id":lid,"passport_id":p["id"],"passport_version":p["version"],"version":1,"status":"draft","created_at":ts,"created_by":user["id"],"updated_at":ts,"updated_by":user["id"],"submitted_at":None,"submitted_by":None,"reviewed_at":None,"reviewed_by":None,"cleared_at":None,"cleared_by":None,"blocked_at":None,"blocked_by":None,"block_reason":"","revoked_at":None,"revoked_by":None,"revocation_reason":"","broker_snapshot":b,"shipper_snapshot":s,"carrier_snapshot":c,"insurance_evidence_snapshot":i,"contact_validation_snapshot":cv,"pickup_instruction_snapshot":pi,"reviews":reviews,"findings":[],"risk_signals":[],"risk_summary":None,"evidence_document_ids":[],"required_review_domains":list(DOMAINS),"unresolved_finding_ids":[],"blocking_reasons":[],"last_material_change_at":None,"notes":""})
        audit=await begin_audit(db.audit_events,user,"party_verification.created",AuditEntityType.PARTY_VERIFICATION_CASE,cid,changed_fields=["id","load_id","passport_id","version","status"])
        try: await db.party_verification_cases.insert_one(doc)
        except Exception: await audit.rejected("duplicate_case"); raise HTTPException(409,"A verification case already exists for this load")
        doc.pop("_id",None); await audit.succeeded(doc); return doc
    @api.put("/party-verification-cases/{cid}")
    async def update(cid:str,data:CaseUpdate,user=Depends(get_current_user)):
        role(user,OPS); c=await one(db,user,cid)
        mutable(c,"update")
        u=data.model_dump(exclude_unset=True); a=await begin_audit(db.audit_events,user,"party_verification.updated",AuditEntityType.PARTY_VERIFICATION_CASE,cid,changed_fields=list(u)+["version"],previous=c); return await replace(db,a,user,c,u)
    async def refresh_case(cid,user,action):
        role(user,OPS); c=await one(db,user,cid)
        mutable(c,"refresh")
        load,p,rate,docs,tenant=await related(db,user,c["load_id"]); b,s,ca,i,cv,pi=snapshots(load,p,rate,docs,tenant); u={"broker_snapshot":b,"shipper_snapshot":s,"carrier_snapshot":ca,"insurance_evidence_snapshot":i,"contact_validation_snapshot":cv,"pickup_instruction_snapshot":pi,"passport_version":p["version"]}; a=await begin_audit(db.audit_events,user,action,AuditEntityType.PARTY_VERIFICATION_CASE,cid,changed_fields=list(u)+["version"],previous=c); return await replace(db,a,user,c,u)
    @api.post("/party-verification-cases/{cid}/refresh")
    async def refresh(cid:str,data:EmptyAction,user=Depends(get_current_user)): return await refresh_case(cid,user,"party_verification.snapshots_refreshed")
    @api.post("/party-verification-cases/{cid}/evaluate")
    async def evaluate_case(cid:str,data:EmptyAction,user=Depends(get_current_user)):
        role(user,OPS|{"safety","compliance","finance"}); c=await one(db,user,cid); mutable(c,"evaluate"); load,p,rate,docs,tenant=await related(db,user,c["load_id"]); fs,risk=evaluate(c,load,rate); target="findings_open" if c["status"]=="review_pending" and any(f["status"]=="open" for f in fs) else c["status"]; u={"findings":fs,"risk_signals":risk["signals"],"risk_summary":risk,"unresolved_finding_ids":[f["id"] for f in fs if f["status"]=="open"],"blocking_reasons":risk["blocking_reasons"],"status":target}; a=await begin_audit(db.audit_events,user,"party_verification.evaluated",AuditEntityType.PARTY_VERIFICATION_CASE,cid,changed_fields=["findings","risk_summary","status","version"],previous=c); return await replace(db,a,user,c,u)
    async def transition(cid,user,target,action,reason="",observed=None,audit=None):
        c=observed or await one(db,user,cid)
        if target not in ALLOWED.get(c["status"],set()): raise HTTPException(409,f"Transition from {c['status']} to {target} is not allowed")
        u={"status":target}; ts=now()
        if target=="review_pending": u.update({"submitted_at":ts,"submitted_by":user["id"],"block_reason":"","cleared_at":None,"cleared_by":None})
        if target=="blocked": u.update({"blocked_at":ts,"blocked_by":user["id"],"block_reason":reason})
        if target=="expired": u.update({"cleared_at":None,"cleared_by":None,"blocking_reasons":["clearance_expired"]})
        if target=="revoked": u.update({"revoked_at":ts,"revoked_by":user["id"],"revocation_reason":reason,"cleared_at":None,"cleared_by":None,"blocking_reasons":["clearance_revoked"]})
        a=audit or await begin_audit(db.audit_events,user,action,AuditEntityType.PARTY_VERIFICATION_CASE,cid,changed_fields=list(u)+["version"],previous=c); return await replace(db,a,user,c,u)
    @api.post("/party-verification-cases/{cid}/submit")
    async def submit(cid:str,data:EmptyAction,user=Depends(get_current_user)): role(user,OPS); return await transition(cid,user,"review_pending","party_verification.submitted")
    @api.put("/party-verification-cases/{cid}/reviews/{domain}")
    async def review(cid:str,domain:ReviewDomain,data:ReviewUpdate,user=Depends(get_current_user)):
        c=await one(db,user,cid); d=domain.value; role(user,DOMAIN_ROLES[d])
        mutable(c,"review")
        if data.result==ReviewResult.WAIVED and user["role"] not in ADMIN: raise HTTPException(403,"Only owner or admin may waive")
        await evidence(db,user,c["load_id"],data.evidence_document_ids); reviews=dict(c["reviews"]); reviews[d]={"domain":d,**data.model_dump(mode="json"),"reviewed_at":now(),"reviewed_by":user["id"],"reviewed_by_role":user["role"]}; a=await begin_audit(db.audit_events,user,"party_verification.review_updated",AuditEntityType.PARTY_VERIFICATION_CASE,cid,changed_fields=["review_domain","version"],previous=c); return await replace(db,a,user,c,{"reviews":reviews,"reviewed_at":now(),"reviewed_by":user["id"]})
    @api.put("/party-verification-cases/{cid}/findings/{fid}")
    async def resolve(cid:str,fid:str,data:FindingUpdate,user=Depends(get_current_user)):
        c=await one(db,user,cid); mutable(c,"finding"); fs=[dict(f) for f in c.get("findings",[])]; f=next((x for x in fs if x["id"]==fid),None)
        if not f: raise HTTPException(404,"Not found")
        role(user,DOMAIN_ROLES[f["domain"]]);
        if data.resolution==FindingResolution.WAIVED and user["role"] not in ADMIN: raise HTTPException(403,"Only owner or admin may waive")
        await evidence(db,user,c["load_id"],data.evidence_document_ids); f.update({"status":"waived" if data.resolution==FindingResolution.WAIVED else "resolved","resolution":data.resolution.value,"resolution_reason":data.reason,"evidence_document_ids":data.evidence_document_ids,"resolved_at":now(),"resolved_by":user["id"],"resolved_by_role":user["role"]}); a=await begin_audit(db.audit_events,user,"party_verification.finding_resolved",AuditEntityType.PARTY_VERIFICATION_CASE,cid,changed_fields=["finding_id","version"],previous=c); return await replace(db,a,user,c,{"findings":fs,"unresolved_finding_ids":[x["id"] for x in fs if x["status"]=="open"]})
    @api.post("/party-verification-cases/{cid}/evidence")
    async def add_evidence(cid:str,data:EvidenceAdd,user=Depends(get_current_user)):
        role(user,OPS|{"safety","compliance","finance"}); c=await one(db,user,cid); mutable(c,"evidence"); await evidence(db,user,c["load_id"],data.document_ids); ids=sorted(set(c.get("evidence_document_ids",[])+data.document_ids)); a=await begin_audit(db.audit_events,user,"party_verification.evidence_added",AuditEntityType.PARTY_VERIFICATION_CASE,cid,changed_fields=["document_id","version"],previous=c); return await replace(db,a,user,c,{"evidence_document_ids":ids})
    @api.post("/party-verification-cases/{cid}/clear")
    async def clear(cid:str,data:EmptyAction,user=Depends(get_current_user)):
        role(user,ADMIN); c=await one(db,user,cid)
        if c["status"] not in {"review_pending","findings_open"}: raise HTTPException(409,"Case cannot be cleared from its current status")
        a=await begin_audit(db.audit_events,user,"party_verification.cleared",AuditEntityType.PARTY_VERIFICATION_CASE,cid,changed_fields=["status","version"],previous=c)
        c=await one(db,user,cid); load,p,rate,docs,tenant=await related(db,user,c["load_id"]); fs,risk=evaluate(c,load,rate); incomplete=[d for d in DOMAINS if c.get("reviews",{}).get(d,{}).get("result") in {None,"pending","mismatch","insufficient_evidence","expired","blocked"}]
        b,s,ca,ins,cv,pi=snapshots(load,p,rate,docs,tenant); drift=any(c.get(k)!=(v) for k,v in (("broker_snapshot",b),("shipper_snapshot",s),("carrier_snapshot",ca),("insurance_evidence_snapshot",ins),("contact_validation_snapshot",cv),("pickup_instruction_snapshot",pi)))
        blockers=[]
        if incomplete: blockers.append("required_review_domain_incomplete")
        if risk["blocking_signal_count"]: blockers.append("unresolved_blocking_finding")
        if risk["critical_signal_count"]: blockers.append("unresolved_critical_signal")
        if not qualified_insurance_documents(docs): blockers.append("insurance_evidence_required")
        extraction_workflow=await db.rate_confirmation_extractions.find(tenant_filter(user,{"load_id":c["load_id"]}),{"_id":0}).to_list(1)
        if (rate_confirmation_required(docs) or extraction_workflow) and not rate: blockers.append("accepted_rate_confirmation_required")
        if p["version"]!=c.get("passport_version"): blockers.append("passport_version_changed")
        if drift: blockers.append("material_snapshot_drift")
        if blockers: await a.rejected(blockers[0]); raise HTTPException(409,{"blocking_reasons":sorted(set(blockers)),"incomplete_review_domains":incomplete})
        try:new_passport_version=await sync_passport(user,c,True)
        except HTTPException as exc: await a.rejected("passport_synchronization_failed"); raise
        ts=now(); u={"status":"cleared","cleared_at":ts,"cleared_by":user["id"],"reviewed_at":ts,"reviewed_by":user["id"],"findings":fs,"risk_summary":risk,"risk_signals":risk["signals"],"blocking_reasons":[],"passport_version":new_passport_version}
        updates={**u,"updated_at":ts,"updated_by":user["id"],"version":c["version"]+1}
        try:r=await db.party_verification_cases.update_one(tenant_filter(user,{"id":c["id"],"status":c["status"],"version":c["version"]}),{"$set":updates})
        except Exception: await a.failed(); raise HTTPException(500,"Database operation failed")
        if not r.matched_count:
            await sync_passport(user,c,False)
            await a.rejected("version_conflict"); raise HTTPException(409,"Verification case changed concurrently")
        await a.succeeded({"id":c["id"],"load_id":c["load_id"],"status":"cleared","version":updates["version"],"passport_id":p["id"]}); return await one(db,user,c["id"])
    @api.post("/party-verification-cases/{cid}/block")
    async def block(cid:str,data:ReasonAction,user=Depends(get_current_user)):
        role(user,ADMIN); current=await one(db,user,cid)
        if "blocked" not in ALLOWED.get(current["status"],set()): raise HTTPException(409,f"Transition from {current['status']} to blocked is not allowed")
        parent=await begin_audit(db.audit_events,user,"party_verification.blocked",AuditEntityType.PARTY_VERIFICATION_CASE,cid,changed_fields=["status","version"],previous=current)
        await preinvalidate_for_load(db,user,current["load_id"],["party_verification"]); out=await transition(cid,user,"blocked","party_verification.blocked",data.reason,current,parent); await sync_passport(user,out,False); return out
    @api.post("/party-verification-cases/{cid}/return-to-review")
    async def return_review(cid:str,data:EmptyAction,user=Depends(get_current_user)): role(user,ADMIN); return await transition(cid,user,"review_pending","party_verification.returned_to_review")
    @api.post("/party-verification-cases/{cid}/expire")
    async def expire(cid:str,data:EmptyAction,user=Depends(get_current_user)):
        role(user,ADMIN); current=await one(db,user,cid)
        if "expired" not in ALLOWED.get(current["status"],set()): raise HTTPException(409,f"Transition from {current['status']} to expired is not allowed")
        parent=await begin_audit(db.audit_events,user,"party_verification.expired",AuditEntityType.PARTY_VERIFICATION_CASE,cid,changed_fields=["status","version"],previous=current)
        await preinvalidate_for_load(db,user,current["load_id"],["party_verification"]); out=await transition(cid,user,"expired","party_verification.expired","",current,parent); await sync_passport(user,out,False); return out
    @api.post("/party-verification-cases/{cid}/revoke")
    async def revoke(cid:str,data:ReasonAction,user=Depends(get_current_user)):
        role(user,ADMIN); current=await one(db,user,cid)
        if "revoked" not in ALLOWED.get(current["status"],set()): raise HTTPException(409,f"Transition from {current['status']} to revoked is not allowed")
        parent=await begin_audit(db.audit_events,user,"party_verification.revoked",AuditEntityType.PARTY_VERIFICATION_CASE,cid,changed_fields=["status","version"],previous=current)
        await preinvalidate_for_load(db,user,current["load_id"],["party_verification"]); out=await transition(cid,user,"revoked","party_verification.revoked",data.reason,current,parent); await sync_passport(user,out,False); return out
