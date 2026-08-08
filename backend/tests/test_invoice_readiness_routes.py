"""Real FastAPI Phase 1G routes using fake collections and DB-backed users."""
import copy,pytest
from types import SimpleNamespace
from fastapi import Header,HTTPException
from fastapi.testclient import TestClient
from test_rate_confirmation_routes import FakeDB,Collection,LOAD,USERS,TA,TB,h,server,extraction,FIELDS

def session(tenant=TA):return {"id":"S1","tenant_id":tenant,"load_id":"L1","version":3,"status":"completed","execution_state":"delivery_confirmed","updated_at":"now","actual_snapshot":{"delivery_confirmed_at":"now","delivery_reference":"REF"},"custody_state":"delivered"}
@pytest.fixture
def api(monkeypatch):
 db=FakeDB()
 for n in ("execution_sessions","execution_events","execution_exceptions","execution_eligibility_cases","pickup_release_cases","invoice_readiness_cases","invoice_packages","invoices","operations","outbox_events","reconciliation_items"):setattr(db,n,Collection(n,db.events))
 db.loads.docs=[{**copy.deepcopy(LOAD),"stage":"Delivered"},{**copy.deepcopy(LOAD),"id":"LB","tenant_id":TB,"stage":"Delivered"}];db.execution_sessions.docs=[session(),{**session(TB),"id":"SB","load_id":"LB"}]
 db.documents.docs=[{"id":"POD","tenant_id":TA,"load_id":"L1","doc_type":"pod","filename":"pod.pdf"},{"id":"RC","tenant_id":TA,"load_id":"L1","doc_type":"rate_con","filename":"rate.pdf"},{"id":"LUMP","tenant_id":TA,"load_id":"L1","doc_type":"lumper","filename":"receipt.pdf"},{"id":"FPOD","tenant_id":TB,"load_id":"LB","doc_type":"pod"}]
 rate=extraction(status="accepted");rate.update({"id":"R1","document_id":"RC","revision":2,"version":2});rate["extracted_fields"]={"total_rate":1200};db.rate_confirmation_extractions.docs=[rate]
 monkeypatch.setattr(server,"db",db);server.app.dependency_overrides.clear()
 async def actor(x_test_user:str=Header("ops")):
  record=await db.users.find_one({"id":USERS.get(x_test_user,USERS["ops"])["id"]})
  if not record:raise HTTPException(401,"User unavailable")
  record.pop("_id",None);return record
 server.app.dependency_overrides[server.get_current_user]=actor;yield TestClient(server.app),db;server.app.dependency_overrides.clear()
def create(c,user="ops",body=None):return c.post("/api/loads/L1/invoice-readiness-case",json=body or {},headers=h(user))
def test_create_server_fields_audit_first_duplicate_and_protection(api):
 c,db=api;r=create(c);assert r.status_code==201,r.text;x=r.json();assert x["id"].startswith("irc_") and x["tenant_id"]==TA and x["version"]==1 and x["status"]=="draft" and "_id" not in x
 assert db.events.index("audit_events.insert")<db.events.index("invoice_readiness_cases.insert") and create(c).status_code==409
 for body in ({"tenant_id":TA},{"status":"ready"},{"billable_total":"1"},{"version":1},{"snapshot":{}}):
  db.invoice_readiness_cases.docs=[];assert create(c,body=body).status_code==422
def test_tenant_isolation_and_no_delete(api):
 c,db=api;x=create(c).json();foreign={**x,"id":"CB","tenant_id":TB,"load_id":"LB"};db.invoice_readiness_cases.docs.append(foreign)
 assert [z["id"] for z in c.get("/api/invoice-readiness-cases",headers=h("ops")).json()]==[x["id"]]
 assert c.get(f"/api/invoice-readiness-cases/{x['id']}",headers=h("foreign")).status_code==404
 assert c.post(f"/api/invoice-readiness-cases/{x['id']}/evaluate",json={"version":1},headers=h("foreign")).status_code==404
 assert c.get("/api/invoice-readiness-cases",headers=h("tenantless")).status_code==403
 assert c.delete(f"/api/invoice-readiness-cases/{x['id']}",headers=h("owner")).status_code==405
def test_evaluate_fail_closed_then_ready_and_deterministic(api):
 c,db=api;x=create(c).json();path=f"/api/invoice-readiness-cases/{x['id']}/evaluate";db.documents.docs=[];r=c.post(path,json={"version":1},headers=h("finance"));assert r.status_code==200 and r.json()["status"]=="blocked" and "pod_present" in [i["type"] for i in r.json()["readiness_items"] if i["result"]=="fail"]
 db.documents.docs=[{"id":"POD","tenant_id":TA,"load_id":"L1","doc_type":"pod"},{"id":"RC","tenant_id":TA,"load_id":"L1","doc_type":"rate_con"}];r=c.post(path,json={"version":2},headers=h("finance"));assert r.status_code==200,r.text;assert r.json()["status"]=="ready" and r.json()["billable_total"]=="1200.00"
 assert c.post(path,json={"version":2},headers=h("finance")).status_code==409
def test_missing_delivery_rate_and_stale_rate_block(api):
 c,db=api;x=create(c).json();db.execution_sessions.docs=[];r=c.post(f"/api/invoice-readiness-cases/{x['id']}/evaluate",json={"version":1},headers=h("finance"));assert "execution_session_current" in [i["type"] for i in r.json()["readiness_items"] if i["result"]=="fail"]
 db.execution_sessions.docs=[session()];db.rate_confirmation_extractions.docs[0]["superseded_by"]="R2";r=c.post(f"/api/invoice-readiness-cases/{x['id']}/evaluate",json={"version":2},headers=h("finance"));assert any(i["type"]=="rate_confirmation_current" and i["result"]=="fail" for i in r.json()["readiness_items"])
def test_accessorial_evidence_role_money_and_race(api):
 c,db=api;x=create(c).json();base=f"/api/invoice-readiness-cases/{x['id']}/accessorials";r=c.post(base,json={"version":1,"type":"lumper","amount":"20.10","evidence_document_ids":[]},headers=h("finance"));assert r.status_code==201 and r.json()["status"]=="evidence_required";aid=r.json()["id"]
 assert c.post(base,json={"version":2,"type":"bogus","amount":1},headers=h("finance")).status_code==422
 for amount in (-1,"NaN","Infinity"):assert c.post(base,json={"version":2,"type":"lumper","amount":amount},headers=h("finance")).status_code==422
 assert c.post(f"{base}/{aid}/approve",json={"version":2},headers=h("finance")).status_code==409
 assert c.post(base,json={"version":2,"type":"lumper","amount":"10.00","evidence_document_ids":["FPOD"]},headers=h("finance")).status_code==404
 r=c.post(base,json={"version":2,"type":"lumper","amount":"10.00","evidence_document_ids":["LUMP"]},headers=h("finance"));aid2=r.json()["id"]
 assert c.post(f"{base}/{aid2}/approve",json={"version":3},headers=h("ops")).status_code==403
 assert c.post(f"{base}/{aid2}/approve",json={"version":3},headers=h("finance")).status_code==200
def test_approval_invoice_package_duplicate_and_precise_claims(api):
 c,db=api;x=create(c).json();cid=x["id"];r=c.post(f"/api/invoice-readiness-cases/{cid}/evaluate",json={"version":1},headers=h("finance"));assert r.json()["status"]=="ready"
 assert c.post(f"/api/invoice-readiness-cases/{cid}/approve",json={"version":2},headers=h("finance")).status_code==403
 r=c.post(f"/api/invoice-readiness-cases/{cid}/approve",json={"version":2},headers=h("owner"));assert r.status_code==200,r.text
 inv=c.post(f"/api/invoice-readiness-cases/{cid}/invoice",json={"version":3},headers=h("owner"));assert inv.status_code==201,inv.text;body=inv.json();assert body["status"]=="ready_for_submission" and body["external_submission_status"]=="not_submitted" and body["amount"]=="1200.00" and "_id" not in body
 package=c.get(f"/api/invoice-packages/{body['package_id']}",headers=h("owner"));assert package.status_code==200 and len(package.json()["canonical_hash"])==64 and "url" not in str(package.json())
 assert c.post(f"/api/invoice-readiness-cases/{cid}/invoice",json={"version":3},headers=h("owner")).status_code==409
def test_audit_failure_and_partial_failure_are_safe(api):
 c,db=api;db.audit_events.fail_insert=True;assert create(c).status_code==503 and not db.invoice_readiness_cases.docs
 db.audit_events.fail_insert=False;x=create(c).json();c.post(f"/api/invoice-readiness-cases/{x['id']}/evaluate",json={"version":1},headers=h("finance"));c.post(f"/api/invoice-readiness-cases/{x['id']}/approve",json={"version":2},headers=h("owner"));db.invoices.fail_insert=True
 r=c.post(f"/api/invoice-readiness-cases/{x['id']}/invoice",json={"version":3},headers=h("owner"));assert r.status_code==503 and len(db.invoice_packages.docs)==1 and not db.invoices.docs

def ready(c,approve=False):
 x=create(c).json();x=c.post(f"/api/invoice-readiness-cases/{x['id']}/evaluate",json={"version":1},headers=h("finance")).json()
 return c.post(f"/api/invoice-readiness-cases/{x['id']}/approve",json={"version":2},headers=h("owner")).json() if approve else x
def test_rc_document_relationship_missing_wrong_load_type_and_tenant_blocks(api):
 c,db=api
 for mutate in (lambda d:setattr(d.documents,"docs",[x for x in d.documents.docs if x["id"]!="RC"]),lambda d:d.documents.docs[1].update({"doc_type":"pod"}),lambda d:d.documents.docs[1].update({"load_id":"LB"}),lambda d:d.documents.docs[1].update({"tenant_id":TB})):
  db.invoice_readiness_cases.docs=[];db.documents.docs=[{"id":"POD","tenant_id":TA,"load_id":"L1","doc_type":"pod"},{"id":"RC","tenant_id":TA,"load_id":"L1","doc_type":"rate_con"}];mutate(db);x=create(c).json();r=c.post(f"/api/invoice-readiness-cases/{x['id']}/evaluate",json={"version":1},headers=h("finance"));assert r.status_code==200 and r.json()["status"]=="blocked" and r.json()["rate_snapshot"] is None
def test_same_amount_new_rate_basis_rejects_final_approval(api):
 c,db=api;x=ready(c);db.documents.docs.append({"id":"RC2","tenant_id":TA,"load_id":"L1","doc_type":"rate_con"});new=copy.deepcopy(db.rate_confirmation_extractions.docs[0]);new.update({"id":"R2","document_id":"RC2","revision":3,"version":3});db.rate_confirmation_extractions.docs.append(new)
 assert c.post(f"/api/invoice-readiness-cases/{x['id']}/approve",json={"version":2},headers=h("owner")).status_code==409
def test_document_material_change_reopens_and_parent_audit_precedes_invalidation(api):
 c,db=api;x=ready(c,True);mark=len(db.events);r=c.post("/api/documents",json={"load_id":"L1","doc_type":"bol","filename":"bol.pdf","url":"mock://bol.pdf"},headers=h("ops"));assert r.status_code==200,r.text
 current=db.invoice_readiness_cases.docs[0];assert current["status"]=="reopened" and current["approved_at"]==x["approved_at"] and current["calculation_snapshot"]==x["calculation_snapshot"]
 segment=db.events[mark:];assert segment.index("audit_events.insert")<segment.index("invoice_readiness_cases.update")<segment.index("documents.insert")
def test_document_invalidation_race_and_audit_failure_prevent_insert(api):
 c,db=api;x=ready(c);before=len(db.documents.docs);db.invoice_readiness_cases.matched_count_override=0;r=c.post("/api/documents",json={"load_id":"L1","doc_type":"bol","filename":"b.pdf","url":"mock://b.pdf"},headers=h("ops"));assert r.status_code==409 and len(db.documents.docs)==before
 db.invoice_readiness_cases.matched_count_override=None;db.invoice_readiness_cases.docs=[x];db.audit_events.fail_insert=True;r=c.post("/api/documents",json={"load_id":"L1","doc_type":"bol","filename":"c.pdf","url":"mock://c.pdf"},headers=h("ops"));assert r.status_code==503 and len(db.documents.docs)==before and db.invoice_readiness_cases.docs[0]["status"]=="ready"
def test_adding_missing_pod_never_auto_approves(api):
 c,db=api;db.documents.docs=[x for x in db.documents.docs if x["id"]!="POD"];x=create(c).json();blocked=c.post(f"/api/invoice-readiness-cases/{x['id']}/evaluate",json={"version":1},headers=h("finance")).json();assert blocked["status"]=="blocked"
 r=c.post("/api/documents",json={"load_id":"L1","doc_type":"pod","filename":"newpod.pdf","url":"mock://newpod.pdf"},headers=h("ops"));assert r.status_code==200 and db.invoice_readiness_cases.docs[0]["status"]=="blocked" and db.invoice_readiness_cases.docs[0]["verdict"]=="blocked"
def test_invoice_rereads_basis_and_reopens_on_delivery_drift(api):
 c,db=api;x=ready(c,True);db.execution_sessions.docs[0]["version"]+=1;r=c.post(f"/api/invoice-readiness-cases/{x['id']}/invoice",json={"version":3},headers=h("owner"));assert r.status_code==409 and not db.invoice_packages.docs and not db.invoices.docs and db.invoice_readiness_cases.docs[0]["status"]=="reopened"
def test_atomic_claim_allows_only_one_invoice_and_orders_artifacts(api):
 c,db=api;x=ready(c,True);mark=len(db.events);first=c.post(f"/api/invoice-readiness-cases/{x['id']}/invoice",json={"version":3},headers=h("owner"));second=c.post(f"/api/invoice-readiness-cases/{x['id']}/invoice",json={"version":3},headers=h("owner"));assert first.status_code==201 and second.status_code==409 and len(db.invoice_packages.docs)==len(db.invoices.docs)==1
 segment=db.events[mark:];assert segment.index("audit_events.insert")<segment.index("invoice_readiness_cases.update")<segment.index("invoice_packages.insert")<segment.index("invoices.insert")
def test_package_failure_sets_reconciliation_and_retry_creates_nothing(api):
 c,db=api;x=ready(c,True);db.invoice_packages.fail_insert=True;r=c.post(f"/api/invoice-readiness-cases/{x['id']}/invoice",json={"version":3},headers=h("owner"));assert r.status_code==503 and not db.invoices.docs and db.invoice_readiness_cases.docs[0]["invoice_creation_state"]=="reconciliation_required"
 assert c.post(f"/api/invoice-readiness-cases/{x['id']}/invoice",json={"version":4},headers=h("owner")).status_code==409 and not db.invoice_packages.docs
def test_creating_claim_blocks_upstream_document_change(api):
 c,db=api;x=ready(c,True);db.invoice_readiness_cases.docs[0]["invoice_creation_state"]="creating";before=len(db.documents.docs);r=c.post("/api/documents",json={"load_id":"L1","doc_type":"pod","filename":"p2.pdf","url":"mock://p2.pdf"},headers=h("ops"));assert r.status_code==409 and len(db.documents.docs)==before
def test_actual_rc_acceptance_and_supersession_reopen_readiness(api):
 c,db=api;x=ready(c,True);new=copy.deepcopy(db.rate_confirmation_extractions.docs[0]);new.update({"id":"R2","status":"review_pending","revision":3,"version":3,"accepted_at":None,"accepted_by":None,"extracted_fields":copy.deepcopy(FIELDS)});db.rate_confirmation_extractions.docs.append(new)
 r=c.post("/api/rate-confirmation-extractions/R2/accept",json={},headers=h("owner"));assert r.status_code==200,r.text;case=db.invoice_readiness_cases.docs[0];assert case["status"]=="reopened" and case["approved_at"]==x["approved_at"] and case["calculation_snapshot"]==x["calculation_snapshot"]
 db.invoice_readiness_cases.docs[0].update({"status":"ready","verdict":"ready","version":case["version"]+1});db.rate_confirmation_extractions.docs[-1]["status"]="accepted";r=c.post("/api/rate-confirmation-extractions/R2/supersede",json={"reason":"replacement"},headers=h("owner"));assert r.status_code==200 and db.invoice_readiness_cases.docs[0]["status"]=="review_pending"
def test_illegal_rc_transition_and_parent_audit_failure_leave_readiness(api):
 c,db=api;x=ready(c);before=copy.deepcopy(db.invoice_readiness_cases.docs[0]);db.rate_confirmation_extractions.docs[0]["status"]="draft";assert c.post("/api/rate-confirmation-extractions/R1/supersede",json={"reason":"x"},headers=h("owner")).status_code==409 and db.invoice_readiness_cases.docs[0]==before
 db.rate_confirmation_extractions.docs[0]["status"]="accepted";db.audit_events.fail_insert=True;assert c.post("/api/rate-confirmation-extractions/R1/supersede",json={"reason":"x"},headers=h("owner")).status_code==503 and db.invoice_readiness_cases.docs[0]==before and db.rate_confirmation_extractions.docs[0]["status"]=="accepted"
def test_phase1f_delivery_exception_reopens_before_primary_mutation(api):
 c,db=api;x=ready(c,True);mark=len(db.events);payload={"version":3,"type":"delivery_confirmation_conflict","category":"delivery","severity":"warning","blocking":True,"title":"Delivery correction"};r=c.post("/api/execution-sessions/S1/exceptions",json=payload,headers=h("ops"));assert r.status_code==201,r.text;assert db.invoice_readiness_cases.docs[0]["status"]=="reopened"
 segment=db.events[mark:];assert segment.index("audit_events.insert")<segment.index("invoice_readiness_cases.update")<segment.index("execution_exceptions.insert")
def test_phase1f_readiness_race_blocks_exception_mutation(api):
 c,db=api;x=ready(c);db.invoice_readiness_cases.matched_count_override=0;payload={"version":3,"type":"delivery_confirmation_conflict","category":"delivery","severity":"warning","blocking":True,"title":"Delivery correction"};r=c.post("/api/execution-sessions/S1/exceptions",json=payload,headers=h("ops"));assert r.status_code==409 and not db.execution_exceptions.docs
def test_accessorial_material_change_reopens_and_preserves_approved_basis(api):
 c,db=api;x=ready(c,True);r=c.post(f"/api/invoice-readiness-cases/{x['id']}/accessorials",json={"version":3,"type":"toll","amount":"5.00"},headers=h("finance"));assert r.status_code==201,r.text;case=db.invoice_readiness_cases.docs[0];assert case["status"]=="reopened" and case["calculation_snapshot"]==x["calculation_snapshot"] and case["basis_history"][-1]["status"]=="approved"
def test_document_insert_failure_leaves_conservative_invalidation(api):
 c,db=api;x=ready(c);db.documents.fail_insert=True;r=c.post("/api/documents",json={"load_id":"L1","doc_type":"bol","filename":"fail.pdf","url":"mock://fail.pdf"},headers=h("ops"));assert r.status_code==500 and db.invoice_readiness_cases.docs[0]["status"]=="review_pending"
def test_rc_invalidation_race_blocks_supersession(api):
 c,db=api;x=ready(c);db.invoice_readiness_cases.matched_count_override=0;r=c.post("/api/rate-confirmation-extractions/R1/supersede",json={"reason":"replacement"},headers=h("owner"));assert r.status_code==409 and db.rate_confirmation_extractions.docs[0]["status"]=="accepted"
def test_phase1f_parent_audit_failure_changes_neither_basis_nor_exception(api):
 c,db=api;x=ready(c);before=copy.deepcopy(db.invoice_readiness_cases.docs[0]);db.audit_events.fail_insert=True;payload={"version":3,"type":"delivery_confirmation_conflict","category":"delivery","severity":"warning","blocking":True,"title":"Delivery correction"};r=c.post("/api/execution-sessions/S1/exceptions",json=payload,headers=h("ops"));assert r.status_code==503 and db.invoice_readiness_cases.docs[0]==before and not db.execution_exceptions.docs
def test_readiness_finalization_race_preserves_artifacts_and_reconciles(api):
 c,db=api;x=ready(c,True);collection=db.invoice_readiness_cases;original=collection.update_one;calls=0
 async def raced(query,update,**kwargs):
  nonlocal calls
  calls+=1
  if calls==2:return SimpleNamespace(matched_count=0,modified_count=0)
  return await original(query,update,**kwargs)
 collection.update_one=raced;r=c.post(f"/api/invoice-readiness-cases/{x['id']}/invoice",json={"version":3},headers=h("owner"));assert r.status_code==409 and len(db.invoice_packages.docs)==len(db.invoices.docs)==1 and collection.docs[0]["invoice_creation_state"]=="reconciliation_required"
 assert c.post(f"/api/invoice-readiness-cases/{x['id']}/invoice",json={"version":4},headers=h("owner")).status_code==409 and len(db.invoice_packages.docs)==len(db.invoices.docs)==1
