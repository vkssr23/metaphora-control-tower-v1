import secrets
from datetime import datetime,timezone
from fastapi import Depends,HTTPException,Query,status
from app.audit import begin_audit
from app.schemas.audit import AuditEntityType
from app.schemas.invoice_readiness import *
from app.tenant import tenant_document,tenant_filter,require_tenant_id
from app.domain.invoice_readiness import evaluate,canonical_hash,evidence_ok,select_current_rate,basis_fingerprint,invalidation_plan
from app.invoice_readiness_invalidation import invalidate_invoice_readiness

FINANCE={"finance","owner","admin"}; OWNER={"owner","admin"}; OPS=FINANCE|{"operations","dispatcher"}
def now():return datetime.now(timezone.utc).isoformat()
def clean(x):
 if x:x.pop("_id",None)
 return x
def permit(user,roles):
 require_tenant_id(user)
 if user.get("role") not in roles:raise HTTPException(403,"Insufficient permission")
async def one(col,user,rid,label):
 x=await col.find_one(tenant_filter(user,{"id":rid}),{"_id":0})
 if not x:raise HTTPException(404,f"{label} not found")
 return clean(x)
async def active_case(db,user,lid):
 items=await db.invoice_readiness_cases.find(tenant_filter(user,{"load_id":lid}),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(50)
 return next((x for x in items if x.get("status")!="invoiced"),None)
async def context(db,user,case):
 load=await db.loads.find_one(tenant_filter(user,{"id":case["load_id"]}),{"_id":0})
 sessions=await db.execution_sessions.find(tenant_filter(user,{"load_id":case["load_id"]}),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(20);session=sessions[0] if sessions else None
 docs=await db.documents.find(tenant_filter(user,{"load_id":case["load_id"]}),{"_id":0}).to_list(200)
 rates=await db.rate_confirmation_extractions.find(tenant_filter(user,{"load_id":case["load_id"]}),{"_id":0}).to_list(50);rate,rate_reason=select_current_rate(case["load_id"],case["tenant_id"],rates,docs)
 exc=await db.execution_exceptions.find(tenant_filter(user,{"load_id":case["load_id"]}),{"_id":0}).to_list(200)
 return load,session,rate,docs,exc,rate_reason
def snapshots(case,load,session,rate,docs,result,stamp,user):
 safe_docs=[{"id":d["id"],"type":d.get("doc_type"),"filename":d.get("filename",""),"uploaded_at":d.get("uploaded_at"),"uploaded_by":d.get("uploaded_by"),"verification":"presence_only_not_authenticity_verified"} for d in sorted(docs,key=lambda x:x["id"])]
 delivery={"load_id":load["id"],"execution_session_id":session.get("id") if session else None,"execution_session_version":session.get("version") if session else None,"execution_status":session.get("status") if session else None,"execution_state":session.get("execution_state") if session else None,"delivered_at":(session or {}).get("actual_snapshot",{}).get("delivery_confirmed_at"),"load_stage":load.get("stage"),"delivery_reference":(session or {}).get("actual_snapshot",{}).get("delivery_reference"),"custody_state":(session or {}).get("custody_state"),"driver_id":load.get("driver_id"),"truck_id":load.get("truck_id")}
 rate_snap={"id":rate.get("id"),"version":rate.get("version"),"revision":rate.get("revision"),"document_id":rate.get("document_id"),"status":rate.get("status"),"base_source":result["base_source"]} if rate else None
 fingerprint=basis_fingerprint(load,session,rate,docs,case.get("accessorial_snapshot",[]),case.get("deduction_snapshot",[]),result["calculation"])
 return {"execution_session_id":delivery["execution_session_id"],"accepted_rate_confirmation_id":rate.get("id") if rate and rate.get("status")=="accepted" else None,"delivery_snapshot":delivery,"document_snapshot":{"documents":safe_docs,"requirements":result["document_requirements"]},"rate_snapshot":rate_snap,"calculation_snapshot":result["calculation"],"financial_basis_fingerprint":fingerprint,"readiness_items":result["readiness_items"],"findings":[{"id":"irf_"+b,"type":b,"status":"open","blocking":True,"summary":b.replace("_"," ")} for b in result["blockers"]],"base_charge":(result["calculation"] or {}).get("base_charge"),"accessorial_total":(result["calculation"] or {}).get("accessorial_total"),"deductions_total":(result["calculation"] or {}).get("deductions_total"),"billable_total":(result["calculation"] or {}).get("billable_total"),"currency":"USD","verdict":result["verdict"],"evaluated_at":stamp,"evaluated_by":user["id"]}
async def mutate(db,user,case,data,action,updates,entity=AuditEntityType.INVOICE_READINESS_CASE):
 if case["version"]!=data.version:raise HTTPException(409,"Invoice readiness case changed concurrently")
 stamp=now();updates={**updates,"version":case["version"]+1,"updated_at":stamp,"updated_by":user["id"],"last_material_change_at":stamp}
 audit=await begin_audit(db.audit_events,user,action,entity,case["id"],changed_fields=sorted(updates),previous=case)
 try:r=await db.invoice_readiness_cases.update_one(tenant_filter(user,{"id":case["id"],"version":case["version"],"status":case["status"]}),{"$set":updates})
 except Exception:await audit.failed("internal_failure");raise HTTPException(503,"Readiness mutation unavailable")
 if not r.matched_count:await audit.rejected("version_conflict");raise HTTPException(409,"Invoice readiness case changed concurrently")
 await audit.succeeded({"id":case["id"],"version":updates["version"],"status":updates.get("status",case["status"])});return await one(db.invoice_readiness_cases,user,case["id"],"Invoice readiness case")
def material_reset(case,reason,user):
 try:plan=invalidation_plan(case,reason,["accessorial"],now(),user["id"])
 except ValueError:raise HTTPException(409,"Invoice creation or issued invoice blocks accessorial mutation")
 if not plan:return {"status":"draft","verdict":"pending"}
 return {k:v for k,v in plan["update"].items() if k not in {"version","updated_at","updated_by","last_material_change_at"}}

def register_invoice_readiness_routes(api,db,get_current_user):
 @api.get("/invoice-readiness-cases")
 async def listing(limit:int=Query(100,ge=1,le=200),user=Depends(get_current_user)):
  return await db.invoice_readiness_cases.find(tenant_filter(user),{"_id":0}).sort([("updated_at",-1),("id",-1)]).to_list(limit)
 @api.get("/invoice-readiness-cases/{cid}")
 async def get_case(cid:str,user=Depends(get_current_user)):return await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case")
 @api.get("/loads/{lid}/invoice-readiness-case")
 async def by_load(lid:str,user=Depends(get_current_user)):
  if not await db.loads.find_one(tenant_filter(user,{"id":lid}),{"_id":0}):raise HTTPException(404,"Load not found")
  case=await active_case(db,user,lid)
  if not case:raise HTTPException(404,"Invoice readiness case not found")
  return clean(case)
 @api.put("/invoice-readiness-cases/{cid}")
 async def update_case(cid:str,data:CaseUpdate,user=Depends(get_current_user)):
  permit(user,FINANCE);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case")
  if "finance_note" not in data.model_fields_set:raise HTTPException(422,"At least one mutable field is required")
  return await mutate(db,user,case,data,"invoice_readiness.updated",{"finance_note":data.finance_note})
 @api.post("/loads/{lid}/invoice-readiness-case",status_code=status.HTTP_201_CREATED)
 async def create(lid:str,data:CaseCreate,user=Depends(get_current_user)):
  permit(user,OPS);load=await db.loads.find_one(tenant_filter(user,{"id":lid}),{"_id":0})
  if not load:raise HTTPException(404,"Load not found")
  if await active_case(db,user,lid):raise HTTPException(409,"An active readiness case already exists")
  stamp=now();cid="irc_"+secrets.token_hex(12);doc=tenant_document(user,{"id":cid,"load_id":lid,"execution_session_id":None,"passport_id":None,"accepted_rate_confirmation_id":None,"version":1,"status":"draft","verdict":"pending","created_at":stamp,"created_by":user["id"],"updated_at":stamp,"updated_by":user["id"],"evaluated_at":None,"evaluated_by":None,"financial_snapshot":{},"financial_basis_fingerprint":None,"approved_basis_fingerprint":None,"basis_history":[],"delivery_snapshot":{},"document_snapshot":{},"rate_snapshot":None,"accessorial_snapshot":[],"deduction_snapshot":[],"calculation_snapshot":None,"readiness_items":[],"findings":[],"evidence_document_ids":[],"base_charge":None,"accessorial_total":None,"deductions_total":None,"billable_total":None,"currency":"USD","invoice_id":None,"invoice_version":None,"invoice_package_id":None,"invoice_creation_state":"none","invoice_creation_operation_id":None,"last_material_change_at":stamp})
  audit=await begin_audit(db.audit_events,user,"invoice_readiness.created",AuditEntityType.INVOICE_READINESS_CASE,cid,changed_fields=["id","load_id","status","version"])
  try:await db.invoice_readiness_cases.insert_one(doc)
  except Exception:await audit.failed("internal_failure");raise HTTPException(503,"Readiness create unavailable")
  await audit.succeeded(doc);return clean(doc)
 async def refresh_case(cid,data,user,action="invoice_readiness.refreshed"):
  permit(user,FINANCE);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case")
  if case["status"] in {"approved","invoiced"}:raise HTTPException(409,"Approved readiness cannot be ordinarily refreshed")
  load,session,rate,docs,exc,rate_reason=await context(db,user,case);acc=case.get("accessorial_snapshot",[]);result=evaluate(load,session,rate,docs,acc,case.get("deduction_snapshot",[]),exc);updates=snapshots(case,load,session,rate,docs,result,now(),user);updates.update({"status":"draft","verdict":"pending"})
  return await mutate(db,user,case,data,action,updates)
 @api.post("/invoice-readiness-cases/{cid}/refresh")
 async def refresh(cid:str,data:VersionAction,user=Depends(get_current_user)):return await refresh_case(cid,data,user)
 @api.post("/invoice-readiness-cases/{cid}/evaluate")
 async def evaluate_case(cid:str,data:VersionAction,user=Depends(get_current_user)):
  permit(user,FINANCE);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case")
  if case["version"]!=data.version:raise HTTPException(409,"Invoice readiness case changed concurrently")
  load,session,rate,docs,exc,rate_reason=await context(db,user,case);result=evaluate(load,session,rate,docs,case.get("accessorial_snapshot",[]),case.get("deduction_snapshot",[]),exc);updates=snapshots(case,load,session,rate,docs,result,now(),user);updates["status"]="ready" if result["verdict"]=="ready" else "blocked"
  return await mutate(db,user,case,data,"invoice_readiness.evaluated",updates)
 @api.post("/invoice-readiness-cases/{cid}/submit-review")
 async def submit(cid:str,data:VersionAction,user=Depends(get_current_user)):
  permit(user,FINANCE);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case")
  if case["status"] not in {"draft","review_required","blocked","reopened"}:raise HTTPException(409,"Invalid readiness lifecycle transition")
  return await mutate(db,user,case,data,"invoice_readiness.submitted_for_review",{"status":"review_pending","verdict":"pending","submitted_for_review_at":now(),"submitted_for_review_by":user["id"]})
 @api.post("/invoice-readiness-cases/{cid}/evidence")
 async def evidence(cid:str,data:EvidenceAdd,user=Depends(get_current_user)):
  permit(user,OPS);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case")
  for did in data.document_ids:
   if not await db.documents.find_one(tenant_filter(user,{"id":did,"load_id":case["load_id"]}),{"_id":0}):raise HTTPException(404,"Evidence document not found")
  ids=sorted(set(case.get("evidence_document_ids",[]))|set(data.document_ids));return await mutate(db,user,case,data,"invoice_readiness.evidence_added",{"evidence_document_ids":ids,"status":"reopened" if case["status"]=="approved" else "draft","verdict":"pending"})
 @api.post("/invoice-readiness-cases/{cid}/accessorials",status_code=201)
 async def add_accessorial(cid:str,data:AccessorialCreate,user=Depends(get_current_user)):
  permit(user,FINANCE);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case")
  if case["version"]!=data.version:raise HTTPException(409,"Invoice readiness case changed concurrently")
  docs=[]
  for did in data.evidence_document_ids:
   d=await db.documents.find_one(tenant_filter(user,{"id":did,"load_id":case["load_id"]}),{"_id":0})
   if not d:raise HTTPException(404,"Evidence document not found")
   docs.append(d)
  stamp=now();acc={"id":"acc_"+secrets.token_hex(12),"type":data.type,"amount":str(data.amount.quantize(__import__('decimal').Decimal('.01'))),"currency":data.currency,"status":"review_pending" if evidence_ok({"type":data.type,"evidence_document_ids":data.evidence_document_ids},docs) else "evidence_required","reason":data.reason,"evidence_document_ids":data.evidence_document_ids,"source":"manual","created_at":stamp,"created_by":user["id"],"reviewed_at":None,"reviewed_by":None,"approved_at":None,"approved_by":None,"rejected_at":None,"rejected_by":None}
  result=await mutate(db,user,case,data,"accessorial.created",{"accessorial_snapshot":[*case.get("accessorial_snapshot",[]),acc],**material_reset(case,"accessorial_changed",user)},AuditEntityType.ACCESSORIAL);return next(x for x in result["accessorial_snapshot"] if x["id"]==acc["id"])
 @api.put("/invoice-readiness-cases/{cid}/accessorials/{aid}")
 async def update_accessorial(cid:str,aid:str,data:AccessorialUpdate,user=Depends(get_current_user)):
  permit(user,FINANCE);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case");items=[dict(x) for x in case.get("accessorial_snapshot",[])];acc=next((x for x in items if x["id"]==aid),None)
  if not acc:raise HTTPException(404,"Accessorial not found")
  if acc.get("status") in {"approved","rejected"}:raise HTTPException(409,"Reviewed accessorial history is immutable")
  updates=data.model_dump(exclude_unset=True);updates.pop("version",None)
  if not updates:raise HTTPException(422,"At least one mutable field is required")
  if "amount" in updates:updates["amount"]=str(updates["amount"].quantize(__import__('decimal').Decimal('.01')))
  if "evidence_document_ids" in updates:
   for did in updates["evidence_document_ids"]:
    if not await db.documents.find_one(tenant_filter(user,{"id":did,"load_id":case["load_id"]}),{"_id":0}):raise HTTPException(404,"Evidence document not found")
  acc.update(updates);acc["status"]="review_pending" if evidence_ok(acc,await db.documents.find(tenant_filter(user,{"load_id":case["load_id"]}),{"_id":0}).to_list(200)) else "evidence_required"
  return await mutate(db,user,case,data,"accessorial.updated",{"accessorial_snapshot":items,**material_reset(case,"accessorial_changed",user)},AuditEntityType.ACCESSORIAL)
 @api.put("/invoice-readiness-cases/{cid}/findings/{fid}")
 async def update_finding(cid:str,fid:str,data:FindingUpdate,user=Depends(get_current_user)):
  permit(user,FINANCE);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case");items=[dict(x) for x in case.get("findings",[])];finding=next((x for x in items if x["id"]==fid),None)
  if not finding:raise HTTPException(404,"Finding not found")
  if data.resolution=="waived" and user.get("role") not in OWNER:raise HTTPException(403,"Only owner or admin may waive")
  finding.update({"status":data.resolution,"resolution_reason":data.reason,"resolved_at":now(),"resolved_by":user["id"]})
  return await mutate(db,user,case,data,"invoice_readiness.finding_resolved",{"findings":items,"status":"review_required","verdict":"review_required"})
 async def decide_acc(cid,aid,data,user,approved):
  permit(user,FINANCE);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case");items=[dict(x) for x in case.get("accessorial_snapshot",[])];acc=next((x for x in items if x["id"]==aid),None)
  if not acc:raise HTTPException(404,"Accessorial not found")
  if approved:
   docs=[]
   for did in acc.get("evidence_document_ids",[]):
    d=await db.documents.find_one(tenant_filter(user,{"id":did,"load_id":case["load_id"]}),{"_id":0});docs.extend([d] if d else [])
   if not evidence_ok(acc,docs):raise HTTPException(409,"Required accessorial evidence is missing")
  stamp=now();acc.update({"status":"approved" if approved else "rejected",("approved_at" if approved else "rejected_at"):stamp,("approved_by" if approved else "rejected_by"):user["id"],"reviewed_at":stamp,"reviewed_by":user["id"]})
  return await mutate(db,user,case,data,"accessorial.approved" if approved else "accessorial.rejected",{"accessorial_snapshot":items,**material_reset(case,"accessorial_changed",user)},AuditEntityType.ACCESSORIAL)
 @api.post("/invoice-readiness-cases/{cid}/accessorials/{aid}/approve")
 async def approve_acc(cid:str,aid:str,data:VersionAction,user=Depends(get_current_user)):return await decide_acc(cid,aid,data,user,True)
 @api.post("/invoice-readiness-cases/{cid}/accessorials/{aid}/reject")
 async def reject_acc(cid:str,aid:str,data:VersionAction,user=Depends(get_current_user)):return await decide_acc(cid,aid,data,user,False)
 @api.post("/invoice-readiness-cases/{cid}/approve")
 async def approve(cid:str,data:VersionAction,user=Depends(get_current_user)):
  permit(user,OWNER);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case")
  if case["status"]!="ready" or case.get("verdict")!="ready":raise HTTPException(409,"Readiness case is not ready")
  load,session,rate,docs,exc,rate_reason=await context(db,user,case);result=evaluate(load,session,rate,docs,case.get("accessorial_snapshot",[]),case.get("deduction_snapshot",[]),exc);fresh=snapshots(case,load,session,rate,docs,result,now(),user)
  if result["verdict"]!="ready" or fresh["financial_basis_fingerprint"]!=case.get("financial_basis_fingerprint"):raise HTTPException(409,"Readiness basis is stale; evaluate again")
  return await mutate(db,user,case,data,"invoice_readiness.approved",{"status":"approved","verdict":"ready","approved_at":now(),"approved_by":user["id"],"approved_basis_fingerprint":fresh["financial_basis_fingerprint"]})
 @api.post("/invoice-readiness-cases/{cid}/block")
 async def block(cid:str,data:ReasonAction,user=Depends(get_current_user)):
  permit(user,FINANCE);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case");return await mutate(db,user,case,data,"invoice_readiness.blocked",{"status":"blocked","verdict":"blocked","block_reason":data.reason,"blocked_at":now(),"blocked_by":user["id"]})
 @api.post("/invoice-readiness-cases/{cid}/reopen")
 async def reopen(cid:str,data:ReasonAction,user=Depends(get_current_user)):
  permit(user,OWNER);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case")
  if case["status"]!="approved":raise HTTPException(409,"Only approved readiness may be reopened")
  return await mutate(db,user,case,data,"invoice_readiness.reopened",{"status":"reopened","verdict":"pending","reopened_at":now(),"reopened_by":user["id"],"reopen_reason":data.reason})
 @api.post("/invoice-readiness-cases/{cid}/invoice",status_code=201)
 async def invoice(cid:str,data:VersionAction,user=Depends(get_current_user)):
  permit(user,OWNER);case=await one(db.invoice_readiness_cases,user,cid,"Invoice readiness case")
  if case["version"]!=data.version:raise HTTPException(409,"Invoice readiness case changed concurrently")
  if case["status"]!="approved" or not case.get("calculation_snapshot") or case.get("invoice_creation_state") not in {None,"none"}:raise HTTPException(409,"Approved unclaimed readiness required")
  load,session,rate,docs,exc,rate_reason=await context(db,user,case);result=evaluate(load,session,rate,docs,case.get("accessorial_snapshot",[]),case.get("deduction_snapshot",[]),exc);fresh=snapshots(case,load,session,rate,docs,result,now(),user)
  if result["verdict"]!="ready" or fresh["financial_basis_fingerprint"]!=case.get("approved_basis_fingerprint"):
   await invalidate_invoice_readiness(db,user,case["load_id"],"invoice_basis_changed",["current_basis"]);raise HTTPException(409,"Approved invoice basis is stale and was reopened")
  stamp=now();iid="inv_"+secrets.token_hex(12);pid="ipk_"+secrets.token_hex(12);operation="icr_"+secrets.token_hex(12)
  audit=await begin_audit(db.audit_events,user,"invoice.created",AuditEntityType.INVOICE,iid,changed_fields=["id","amount","status","package_id"])
  claim=await db.invoice_readiness_cases.update_one(tenant_filter(user,{"id":cid,"version":case["version"],"status":"approved","invoice_creation_state":case.get("invoice_creation_state")}),{"$set":{"invoice_creation_state":"creating","invoice_creation_operation_id":operation,"reserved_invoice_id":iid,"reserved_package_id":pid,"version":case["version"]+1,"updated_at":stamp,"updated_by":user["id"]}})
  if not claim.matched_count:await audit.rejected("invoice_creation_claim_conflict");raise HTTPException(409,"Invoice creation already claimed or readiness changed")
  claimed_version=case["version"]+1;docids=sorted({d.get("id") for d in fresh.get("document_snapshot",{}).get("documents",[]) if d.get("id")});package=tenant_document(user,{"id":pid,"readiness_case_id":cid,"readiness_case_version":claimed_version,"financial_basis_fingerprint":fresh["financial_basis_fingerprint"],"load_id":case["load_id"],"invoice_id":iid,"rate_snapshot":fresh["rate_snapshot"],"calculation_snapshot":fresh["calculation_snapshot"],"document_ids":docids,"status":"ready","created_at":stamp,"created_by":user["id"]});package["canonical_hash"]=canonical_hash(package)
  async def reconcile(reason):
   await db.invoice_readiness_cases.update_one(tenant_filter(user,{"id":cid,"invoice_creation_operation_id":operation}),{"$set":{"invoice_creation_state":"reconciliation_required","invoice_creation_failure_reason":reason,"updated_at":now(),"updated_by":user["id"]}})
  try:await db.invoice_packages.insert_one(package)
  except Exception:await reconcile("package_failure");await audit.failed("package_failure");raise HTTPException(503,"Invoice package creation unavailable; claim requires reconciliation")
  inv=tenant_document(user,{"id":iid,"load_id":case["load_id"],"readiness_case_id":cid,"readiness_case_version":claimed_version,"financial_basis_fingerprint":fresh["financial_basis_fingerprint"],"package_id":pid,"amount":fresh["calculation_snapshot"]["billable_total"],"currency":"USD","status":"ready_for_submission","external_submission_status":"not_submitted","created_at":stamp,"created_by":user["id"],"version":1})
  try:await db.invoices.insert_one(inv)
  except Exception:await reconcile("invoice_failure");await audit.failed("invoice_failure");raise HTTPException(503,"Invoice creation failed; package and claim preserved for reconciliation")
  r=await db.invoice_readiness_cases.update_one(tenant_filter(user,{"id":cid,"version":claimed_version,"status":"approved","invoice_creation_state":"creating","invoice_creation_operation_id":operation}),{"$set":{"status":"invoiced","invoice_creation_state":"ready","invoice_id":iid,"invoice_version":1,"invoice_package_id":pid,"version":claimed_version+1,"updated_at":stamp,"updated_by":user["id"]}})
  if not r.matched_count:await reconcile("readiness_finalize_race");await audit.failed("readiness_finalize_race");raise HTTPException(409,"Invoice preserved; readiness finalization requires reconciliation")
  await audit.succeeded({"id":iid,"status":"ready_for_submission","package_id":pid});return clean(inv)
 @api.get("/invoice-packages/{pid}")
 async def get_package(pid:str,user=Depends(get_current_user)):return await one(db.invoice_packages,user,pid,"Invoice package")
