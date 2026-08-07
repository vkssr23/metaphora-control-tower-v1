"""Tenant-scoped, audit-first Phase 1B rate-confirmation workflow."""
import uuid
from fastapi import Depends, HTTPException, Query
from app.audit import begin_audit
from app.schemas.audit import AuditEntityType
from app.tenant import tenant_filter, tenant_document
from app.domain.load_passports import build_preinvalidation, bounded_load_snapshot, calculate_profitability, material_categories, utc_now
from app.domain.rate_confirmations import compare_rate_confirmation, validate_corrected_value, LOAD_FIELD_MAP, FINANCIAL
from app.schemas.rate_confirmations import ExtractionCreate, ExtractionUpdate, ConfidenceUpdate, CompareAction, SubmitAction, AcceptAction, RejectAction, SupersedeAction, ResolutionUpdate, ResolutionStatus
from app.domain.party_verification import build_case_preinvalidation, build_passport_preinvalidation

ADMIN={"owner","admin"}; OPS=ADMIN|{"operations","dispatcher"}; FINANCE=ADMIN|{"finance"}
def _role(user,roles):
    if user.get("role") not in roles: raise HTTPException(403,"Insufficient permission")
def _id(): return f"rcx_{uuid.uuid4().hex}"
def _clean(d):
    if d: d.pop("_id",None)
    return d
async def _one(db,user,eid):
    d=await db.rate_confirmation_extractions.find_one(tenant_filter(user,{"id":eid}),{"_id":0})
    if not d: raise HTTPException(404,"Not found")
    return d
async def _load(db,user,lid):
    d=await db.loads.find_one(tenant_filter(user,{"id":lid}),{"_id":0})
    if not d: raise HTTPException(404,"Not found")
    return d
async def _replace(db,audit,user,e,updates,operation):
    now=utc_now(); updates={**updates,"updated_at":now,"updated_by":user["id"],"version":e["version"]+1}
    try: result=await db.rate_confirmation_extractions.update_one(tenant_filter(user,{"id":e["id"],"status":e["status"],"version":e["version"]}),{"$set":updates})
    except Exception:
        await audit.failed("internal_failure"); raise HTTPException(500,"Database operation failed")
    if not result.matched_count:
        await audit.rejected("version_conflict"); raise HTTPException(409,"Extraction changed concurrently")
    await audit.succeeded({"id":e["id"],"version":updates["version"],"status":updates.get("status",e["status"])})
    return await _one(db,user,e["id"])
def _snapshot(doc):
    return {k:doc.get(k) for k in ("id","load_id","doc_type","filename","uploaded_at","uploaded_by") if k in doc}
def _merge_resolutions(result,resolutions):
    by_id={r.get("discrepancy_id"):r for r in resolutions}
    for d in result["discrepancies"]:
        if d["id"] in by_id: d.update({"resolution_status":by_id[d["id"]]["resolution"],"reviewer_decision":by_id[d["id"]]["decision"]})
    return result

def register_rate_confirmation_routes(api,db,get_current_user):
    @api.get("/rate-confirmation-extractions")
    async def list_all(limit:int=Query(100,ge=1,le=200),user=Depends(get_current_user)):
        return await db.rate_confirmation_extractions.find(tenant_filter(user),{"_id":0}).sort([("created_at",-1),("id",-1)]).to_list(limit)
    @api.get("/rate-confirmation-extractions/{eid}")
    async def get_one(eid:str,user=Depends(get_current_user)): return await _one(db,user,eid)
    @api.get("/loads/{lid}/rate-confirmation-extractions")
    async def list_load(lid:str,limit:int=Query(100,ge=1,le=200),user=Depends(get_current_user)):
        await _load(db,user,lid); return await db.rate_confirmation_extractions.find(tenant_filter(user,{"load_id":lid}),{"_id":0}).sort([("created_at",-1),("id",-1)]).to_list(limit)
    @api.get("/documents/{did}/rate-confirmation-extractions")
    async def list_doc(did:str,limit:int=Query(100,ge=1,le=200),user=Depends(get_current_user)):
        if not await db.documents.find_one(tenant_filter(user,{"id":did}),{"_id":0}): raise HTTPException(404,"Not found")
        return await db.rate_confirmation_extractions.find(tenant_filter(user,{"document_id":did}),{"_id":0}).sort([("revision",-1),("id",-1)]).to_list(limit)
    @api.post("/loads/{lid}/rate-confirmation-extractions",status_code=201)
    async def create(lid:str,data:ExtractionCreate,user=Depends(get_current_user)):
        _role(user,OPS); load=await _load(db,user,lid); doc=await db.documents.find_one(tenant_filter(user,{"id":data.document_id}),{"_id":0})
        if not doc: raise HTTPException(404,"Not found")
        if doc.get("load_id")!=lid: raise HTTPException(409,"Document belongs to another load")
        if doc.get("doc_type")!="rate_con": raise HTTPException(409,"Document is not a rate confirmation")
        if data.source.value=="structured_import" and user.get("role") not in ADMIN: raise HTTPException(403,"Structured import requires owner or admin")
        prior=await db.rate_confirmation_extractions.find(tenant_filter(user,{"document_id":doc["id"]}),{"_id":0}).sort("revision",-1).to_list(1); revision=(prior[0]["revision"]+1) if prior else 1; now=utc_now(); eid=_id()
        record=tenant_document(user,{"id":eid,"load_id":lid,"document_id":doc["id"],"revision":revision,"status":"draft","source":data.source.value,"created_at":now,"created_by":user["id"],"updated_at":now,"updated_by":user["id"],"submitted_at":None,"submitted_by":None,"reviewed_at":None,"reviewed_by":None,"accepted_at":None,"accepted_by":None,"rejected_at":None,"rejected_by":None,"rejection_reason":"","extracted_fields":data.extracted_fields.model_dump(mode="json",exclude_none=True),"comparison_result":None,"discrepancies":[],"reviewer_resolutions":[],"accepted_snapshot":None,"source_document_snapshot":_snapshot(doc),"extraction_confidence":data.extraction_confidence,"notes":data.notes,"version":1})
        audit=await begin_audit(db.audit_events,user,"rate_confirmation.extraction_created",AuditEntityType.RATE_CONFIRMATION_EXTRACTION,eid,changed_fields=["load_id","document_id","revision","status","version"])
        try: await db.rate_confirmation_extractions.insert_one(record)
        except Exception: await audit.failed("internal_failure"); raise HTTPException(500,"Database operation failed")
        _clean(record); await audit.succeeded({"id":eid,"load_id":lid,"document_id":doc["id"],"revision":revision,"version":1}); return record
    @api.put("/rate-confirmation-extractions/{eid}")
    async def update(eid:str,data:ExtractionUpdate,user=Depends(get_current_user)):
        _role(user,OPS); e=await _one(db,user,eid)
        if e["status"]!="draft": raise HTTPException(409,"Only draft extractions may be edited")
        updates=data.model_dump(mode="json",exclude_unset=True); 
        if data.extracted_fields is not None: updates["extracted_fields"]=data.extracted_fields.model_dump(mode="json",exclude_none=True)
        audit=await begin_audit(db.audit_events,user,"rate_confirmation.extraction_updated",AuditEntityType.RATE_CONFIRMATION_EXTRACTION,eid,changed_fields=list(updates)+["version"],previous=e)
        return await _replace(db,audit,user,e,updates,"extraction update")
    @api.put("/rate-confirmation-extractions/{eid}/confidence")
    async def update_confidence(eid:str,data:ConfidenceUpdate,user=Depends(get_current_user)):
        _role(user,ADMIN); e=await _one(db,user,eid)
        if e["status"]!="draft": raise HTTPException(409,"Only draft extractions may be edited")
        if e["source"]!="structured_import": raise HTTPException(409,"Confidence is only supported for structured imports")
        audit=await begin_audit(db.audit_events,user,"rate_confirmation.extraction_confidence_updated",AuditEntityType.RATE_CONFIRMATION_EXTRACTION,eid,changed_fields=["version"],previous=e)
        return await _replace(db,audit,user,e,{"extraction_confidence":data.extraction_confidence},"confidence update")
    @api.post("/rate-confirmation-extractions/{eid}/compare")
    async def compare(eid:str,data:CompareAction,user=Depends(get_current_user)):
        _role(user,OPS|FINANCE); e=await _one(db,user,eid)
        if e["status"] in {"accepted","superseded"}: raise HTTPException(409,"Final extraction cannot be recalculated")
        load=await _load(db,user,e["load_id"]); result=_merge_resolutions(compare_rate_confirmation(e["extracted_fields"],load),e.get("reviewer_resolutions",[])); target="discrepancies_found" if result["discrepancies"] and e["status"]!="draft" else e["status"]
        audit=await begin_audit(db.audit_events,user,"rate_confirmation.compared",AuditEntityType.RATE_CONFIRMATION_EXTRACTION,eid,changed_fields=["comparison_result","discrepancies","status","version"],previous=e)
        return await _replace(db,audit,user,e,{"comparison_result":result,"discrepancies":result["discrepancies"],"status":target},"comparison")
    @api.post("/rate-confirmation-extractions/{eid}/submit")
    async def submit(eid:str,data:SubmitAction,user=Depends(get_current_user)):
        _role(user,OPS); e=await _one(db,user,eid)
        if e["status"] not in {"draft","discrepancies_found","rejected"}: raise HTTPException(409,"Invalid extraction transition")
        load=await _load(db,user,e["load_id"]); result=_merge_resolutions(compare_rate_confirmation(e["extracted_fields"],load),e.get("reviewer_resolutions",[])); now=utc_now(); target="discrepancies_found" if result["discrepancies"] else "review_pending"
        audit=await begin_audit(db.audit_events,user,"rate_confirmation.submitted",AuditEntityType.RATE_CONFIRMATION_EXTRACTION,eid,changed_fields=["status","submitted_at","submitted_by","comparison_result","version"],previous=e)
        return await _replace(db,audit,user,e,{"status":target,"submitted_at":now,"submitted_by":user["id"],"comparison_result":result,"discrepancies":result["discrepancies"],"rejection_reason":""},"submit")
    @api.put("/rate-confirmation-extractions/{eid}/discrepancies/{did}")
    async def resolve(eid:str,did:str,data:ResolutionUpdate,user=Depends(get_current_user)):
        e=await _one(db,user,eid)
        if e["status"] not in {"review_pending","discrepancies_found"}: raise HTTPException(409,"Extraction is not under review")
        disc=next((d for d in e.get("discrepancies",[]) if d["id"]==did),None)
        if not disc: raise HTTPException(404,"Not found")
        role=user.get("role"); financial=disc["type"] in FINANCIAL
        if role not in ADMIN and not (financial and role=="finance") and not (not financial and role in OPS): raise HTTPException(403,"Discrepancy belongs to another review domain")
        if data.resolution==ResolutionStatus.WAIVED and role not in ADMIN: raise HTTPException(403,"Only owner or admin may waive")
        payload=data.model_dump(mode="json")
        if data.decision=="corrected_value":
            try: payload["corrected_value"]=validate_corrected_value(disc["field"],data.corrected_value)
            except ValueError as exc: raise HTTPException(422,str(exc)) from exc
        now=utc_now(); resolution={"discrepancy_id":did,"discrepancy_type":disc["type"],**payload,"resolved_at":now,"resolved_by":user["id"],"resolved_by_role":role}; resolutions=[r for r in e.get("reviewer_resolutions",[]) if r.get("discrepancy_id")!=did]+[resolution]; discs=[({**d,"resolution_status":data.resolution.value,"reviewer_decision":data.decision} if d["id"]==did else d) for d in e["discrepancies"]]
        audit=await begin_audit(db.audit_events,user,"rate_confirmation.discrepancy_resolved",AuditEntityType.RATE_CONFIRMATION_EXTRACTION,eid,changed_fields=["discrepancy_id","version"],previous=e)
        return await _replace(db,audit,user,e,{"reviewer_resolutions":resolutions,"discrepancies":discs,"reviewed_at":now,"reviewed_by":user["id"]},"resolve discrepancy")
    @api.post("/rate-confirmation-extractions/{eid}/reject")
    async def reject(eid:str,data:RejectAction,user=Depends(get_current_user)):
        _role(user,ADMIN); e=await _one(db,user,eid)
        if e["status"] not in {"review_pending","discrepancies_found"}: raise HTTPException(409,"Invalid extraction transition")
        now=utc_now(); audit=await begin_audit(db.audit_events,user,"rate_confirmation.rejected",AuditEntityType.RATE_CONFIRMATION_EXTRACTION,eid,changed_fields=["status","rejection_reason","version"],previous=e)
        return await _replace(db,audit,user,e,{"status":"rejected","rejected_at":now,"rejected_by":user["id"],"rejection_reason":data.reason},"reject")
    @api.post("/rate-confirmation-extractions/{eid}/return-to-review")
    async def returned(eid:str,data:SubmitAction,user=Depends(get_current_user)):
        _role(user,OPS); e=await _one(db,user,eid)
        if e["status"]!="rejected": raise HTTPException(409,"Invalid extraction transition")
        audit=await begin_audit(db.audit_events,user,"rate_confirmation.returned_to_review",AuditEntityType.RATE_CONFIRMATION_EXTRACTION,eid,changed_fields=["status","version"],previous=e)
        return await _replace(db,audit,user,e,{"status":"review_pending","rejection_reason":""},"return to review")
    @api.post("/rate-confirmation-extractions/{eid}/accept")
    async def accept(eid:str,data:AcceptAction,user=Depends(get_current_user)):
        _role(user,ADMIN); e=await _one(db,user,eid)
        if e["status"] not in {"review_pending","discrepancies_found"}: raise HTTPException(409,"Invalid extraction transition")
        load=await _load(db,user,e["load_id"]); doc=await db.documents.find_one(tenant_filter(user,{"id":e["document_id"],"load_id":e["load_id"],"doc_type":"rate_con"}),{"_id":0})
        if not doc: raise HTTPException(404,"Not found")
        result=_merge_resolutions(compare_rate_confirmation(e["extracted_fields"],load),e.get("reviewer_resolutions",[])); resolutions={r["discrepancy_id"]:r for r in e.get("reviewer_resolutions",[])}
        unresolved=[d for d in result["discrepancies"] if d["severity"]=="blocking" and (d["id"] not in resolutions or resolutions[d["id"]]["resolution"]=="unresolved")]
        if unresolved: raise HTTPException(409,{"blocking_discrepancy_types":sorted({d["type"] for d in unresolved})})
        updates={}; selected=[]
        for d in result["discrepancies"]:
            r=resolutions.get(d["id"]); lf=LOAD_FIELD_MAP.get(d["field"])
            if r and d["field"] in {"pickup_location","delivery_location"} and r["decision"]=="use_document_value":
                prefix=d["field"].split("_")[0]
                for suffix,target in (("address","address"),("city","city"),("state","state"),("postal_code","zip")):
                    value=e["extracted_fields"].get(f"{prefix}_{suffix}")
                    if value is not None: updates[f"{prefix}_{target}"]=value; selected.append(f"{prefix}_{target}")
                continue
            if r and d["field"] in {"pickup_date","pickup_time_start","delivery_date","delivery_time_start"} and r["decision"]=="use_document_value":
                prefix=d["field"].split("_")[0]; date=e["extracted_fields"].get(f"{prefix}_date"); tm=e["extracted_fields"].get(f"{prefix}_time_start","00:00")
                if date: updates[f"{prefix}_appt"]=f"{date}T{tm}:00" if len(tm)==5 else f"{date}T{tm}"; selected.append(f"{prefix}_appt")
                continue
            if not r or not lf or r["decision"]=="keep_load_value": continue
            value=r.get("corrected_value") if r["decision"]=="corrected_value" else d["document_value"]
            updates[lf]=value; selected.append(lf)
        material=sorted(set(selected)); audit=await begin_audit(db.audit_events,user,"rate_confirmation.accepted",AuditEntityType.RATE_CONFIRMATION_EXTRACTION,eid,changed_fields=["status","version"]+material,previous=e); passport=await db.load_passports.find_one(tenant_filter(user,{"load_id":e["load_id"]}),{"_id":0}); invalidation=None
        case_collection=getattr(db,"party_verification_cases",None); verification_case=None; verification_plan=None
        if case_collection is not None:
            verification_case=await case_collection.find_one(tenant_filter(user,{"load_id":e["load_id"],"status":"cleared"}),{"_id":0})
        if verification_case:
            verification_plan=build_case_preinvalidation(verification_case,["rate_confirmation"],user["id"],utc_now()); va=await begin_audit(db.audit_events,user,"party_verification.material_change_invalidated",AuditEntityType.PARTY_VERIFICATION_CASE,verification_case["id"],changed_fields=["rate_confirmation","status","version"],previous=verification_case)
            vr=await case_collection.update_one(tenant_filter(user,verification_plan["query"]),{"$set":verification_plan["update"]})
            if not vr.matched_count: await va.rejected("version_conflict"); await audit.rejected("verification_version_conflict"); raise HTTPException(409,"Verification case changed concurrently; rate confirmation was not accepted")
            await va.succeeded({"id":verification_case["id"],"load_id":e["load_id"],"status":"review_pending","version":verification_plan["update"]["version"]})
        if passport and (material or verification_plan):
            if verification_plan:
                pp=build_passport_preinvalidation(passport,verification_plan["effects"],user["id"],utc_now()); invalidation={"required":True,"query":pp["query"],"update":pp["update"],"new_version":pp["update"]["version"]}
            else: invalidation=build_preinvalidation(passport,material_categories(material),user["id"],utc_now())
            if invalidation["required"]:
                ia=await begin_audit(db.audit_events,user,"load_passport.material_change_invalidated",AuditEntityType.LOAD_PASSPORT,passport["id"],changed_fields=material+["status","version"],previous=passport); ir=await db.load_passports.update_one(tenant_filter(user,invalidation["query"]),{"$set":invalidation["update"]})
                if not ir.matched_count: await ia.rejected("version_conflict"); await audit.rejected("passport_version_conflict"); raise HTTPException(409,"Passport changed concurrently; load was not updated")
                await ia.succeeded({"id":passport["id"],"status":"review_pending","version":invalidation["new_version"]})
        if updates:
            if "rate" in updates or "miles" in updates: updates["rpm"]=round(float(updates.get("rate",load.get("rate",0)))/float(updates.get("miles",load.get("miles",0))),2) if float(updates.get("miles",load.get("miles",0)))>0 else 0
            updates["updated_at"]=utc_now()
            try: lr=await db.loads.update_one(tenant_filter(user,{"id":e["load_id"]}),{"$set":updates})
            except Exception:
                await audit.failed("load_update_failed"); raise HTTPException(500,"Database operation failed")
            if not lr.matched_count: await audit.failed("load_update_failed"); raise HTTPException(500,"Database operation failed")
        now=utc_now(); accepted={"extraction_id":eid,"revision":e["revision"],"document_id":e["document_id"],"accepted_at":now,"accepted_by":user["id"],"extracted_fields":e["extracted_fields"],"comparison_result":result,"reviewer_resolutions":e.get("reviewer_resolutions",[]),"canonical_fields_updated":material}
        final=await _replace(db,audit,user,e,{"status":"accepted","accepted_at":now,"accepted_by":user["id"],"accepted_snapshot":accepted,"comparison_result":result,"discrepancies":result["discrepancies"]},"accept")
        if passport:
            current={**load,**updates}; cps=[dict(c) for c in passport.get("checkpoints",[])];
            for cp in cps:
                if cp.get("type")=="rate_confirmation": cp.update({"status":"pass","checked_at":now,"checked_by":user["id"],"checked_by_role":user["role"],"source":"system","evidence_document_ids":[e["document_id"]]})
            sync={"rate_confirmation":{"document_id":e["document_id"],"extraction_id":eid,"extraction_revision":e["revision"],"accepted_at":now,"accepted_reviewer":user["id"],"source":"internal_administrative_review"},"load_snapshot":bounded_load_snapshot(current),"checkpoints":cps}
            if "rate" in updates or "miles" in updates or "deadhead_miles" in updates: sync["profitability_snapshot"]=calculate_profitability(current,await db.assumptions.find_one(tenant_filter(user,{"id":"default"}),{"_id":0}) or {})
            query={"id":passport["id"]};
            if invalidation and invalidation.get("required"): query.update({"version":invalidation["new_version"],"status":"review_pending"})
            await db.load_passports.update_one(tenant_filter(user,query),{"$set":sync})
        return final
    @api.post("/rate-confirmation-extractions/{eid}/supersede")
    async def supersede(eid:str,data:SupersedeAction,user=Depends(get_current_user)):
        _role(user,ADMIN); e=await _one(db,user,eid)
        if e["status"]!="accepted": raise HTTPException(409,"Only accepted extraction may be superseded")
        audit=await begin_audit(db.audit_events,user,"rate_confirmation.superseded",AuditEntityType.RATE_CONFIRMATION_EXTRACTION,eid,changed_fields=["status","version"],previous=e)
        return await _replace(db,audit,user,e,{"status":"superseded","superseded_at":utc_now(),"superseded_by":user["id"],"supersession_reason":data.reason},"supersede")
