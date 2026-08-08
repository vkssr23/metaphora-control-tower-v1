"""Actual Phase 1B FastAPI routes with isolated fake collections and users."""
import copy, os
from types import SimpleNamespace
os.environ.update({"JWT_SECRET":"isolated-test-only-secret-value-over-32-characters","MONGO_URL":"mongodb://127.0.0.1:1/no-network-test","DB_NAME":"isolated","CORS_ORIGINS":"http://localhost:3000","APP_ENV":"test","ALLOW_SEED_ENDPOINT":"false"})
import pytest
from fastapi import Header, HTTPException
from fastapi.testclient import TestClient
import server
from app.domain.rate_confirmations import compare_rate_confirmation

TA="ten_"+"a"*32; TB="ten_"+"b"*32
USERS={
 "ops":{"id":"U-ops","email":"ops@example.test","name":"Ops","role":"operations","tenant_id":TA},
 "finance":{"id":"U-fin","email":"fin@example.test","name":"Finance","role":"finance","tenant_id":TA},
 "owner":{"id":"U-owner","email":"owner@example.test","name":"Owner","role":"owner","tenant_id":TA},
 "viewer":{"id":"U-view","email":"view@example.test","name":"Viewer","role":"viewer","tenant_id":TA},
 "foreign":{"id":"U-foreign","email":"foreign@example.test","name":"Foreign","role":"owner","tenant_id":TB},
 "tenantless":{"id":"U-none","email":"none@example.test","name":"None","role":"owner"},
}
def nested(doc,key):
 value=doc
 for part in key.split("."):
  if not isinstance(value,dict): return None
  value=value.get(part)
 return value
def matches(doc,query):
 for key,wanted in (query or {}).items():
  actual=nested(doc,key)
  if isinstance(wanted,dict) and "$in" in wanted:
   if actual not in wanted["$in"]: return False
  elif actual!=wanted: return False
 return True
class Cursor:
 def __init__(self,docs): self.docs=[copy.deepcopy(d) for d in docs]
 def sort(self,spec,direction=None):
  pairs=spec if isinstance(spec,list) else [(spec,direction)]
  for key,direction in reversed(pairs): self.docs.sort(key=lambda d:(nested(d,key) is not None,nested(d,key)),reverse=direction<0)
  return self
 async def to_list(self,length): return [copy.deepcopy(d) for d in self.docs[:length]]
class Collection:
 def __init__(self,name,events,docs=None): self.name=name; self.events=events; self.docs=[copy.deepcopy(d) for d in docs or []]; self.fail_insert=False; self.fail_update=False; self.matched_count_override=None; self.update_calls=[]
 async def find_one(self,query,*args):
  d=next((x for x in self.docs if matches(x,query)),None); return copy.deepcopy(d) if d else None
 def find(self,query=None,*args,**kwargs): return Cursor([d for d in self.docs if matches(d,query)])
 async def insert_one(self,doc):
  self.events.append(f"{self.name}.insert")
  if self.fail_insert: raise RuntimeError("private database failure")
  stored=copy.deepcopy(doc); stored.setdefault("_id","mongo-private"); self.docs.append(stored); return SimpleNamespace(inserted_id="fake")
 async def update_one(self,query,update,**kwargs):
  self.events.append(f"{self.name}.update"); self.update_calls.append((copy.deepcopy(query),copy.deepcopy(update)))
  if self.fail_update: raise RuntimeError("private database failure")
  found=next((d for d in self.docs if matches(d,query)),None); count=(1 if found else 0) if self.matched_count_override is None else self.matched_count_override
  if count and found: found.update(copy.deepcopy(update.get("$set",{})))
  return SimpleNamespace(matched_count=count,modified_count=count)
class FakeDB:
 def __init__(self):
  self.events=[]
  for n in ("users","loads","documents","rate_confirmation_extractions","load_passports","assumptions","audit_events"): setattr(self,n,Collection(n,self.events))
  self.users.docs=[copy.deepcopy(v) for v in USERS.values()]

LOAD={"id":"L1","tenant_id":TA,"rate":1200,"miles":500,"broker":"Acme","customer":"Ref","commodity":"Food","weight":42000,"equipment_type":"Dry Van","pickup_address":"1 Main","pickup_city":"Chicago","pickup_state":"IL","pickup_zip":"60601","pickup_appt":"2026-08-10T08:00:00","delivery_address":"2 Oak","delivery_city":"Boston","delivery_state":"MA","delivery_zip":"02108","delivery_appt":"2026-08-11T09:00:00","stage":"Assigned"}
DOC={"id":"DOC1","tenant_id":TA,"load_id":"L1","doc_type":"rate_con","filename":"rate.pdf","url":"mock://rate.pdf","uploaded_at":"now","uploaded_by":"U-ops"}
FIELDS={"total_rate":1200,"loaded_miles":500,"broker_name":"Acme","customer_reference":"Ref","commodity":"Food","weight":42000,"equipment_type":"Dry Van","pickup_address":"1 Main","pickup_city":"Chicago","pickup_state":"IL","pickup_postal_code":"60601","pickup_date":"2026-08-10","pickup_time_start":"08:00","delivery_address":"2 Oak","delivery_city":"Boston","delivery_state":"MA","delivery_postal_code":"02108","delivery_date":"2026-08-11","delivery_time_start":"09:00"}
def extraction(status="draft",source="manual",fields=None,tenant=TA):
 return {"id":"rcx_one","tenant_id":tenant,"load_id":"L1","document_id":"DOC1","revision":1,"status":status,"source":source,"created_at":"2026-01-01","created_by":"U-ops","updated_at":"2026-01-01","updated_by":"U-ops","submitted_at":None,"submitted_by":None,"reviewed_at":None,"reviewed_by":None,"accepted_at":None,"accepted_by":None,"rejected_at":None,"rejected_by":None,"rejection_reason":"","extracted_fields":copy.deepcopy(fields if fields is not None else FIELDS),"comparison_result":None,"discrepancies":[],"reviewer_resolutions":[],"accepted_snapshot":None,"source_document_snapshot":{"id":"DOC1"},"extraction_confidence":{},"notes":"","version":1}
@pytest.fixture
def api(monkeypatch):
 db=FakeDB(); db.loads.docs=[copy.deepcopy(LOAD),{**copy.deepcopy(LOAD),"id":"L2"},{**copy.deepcopy(LOAD),"tenant_id":TB,"id":"LB"}]; db.documents.docs=[copy.deepcopy(DOC),{**copy.deepcopy(DOC),"id":"DOC2","load_id":"L2"},{**copy.deepcopy(DOC),"id":"POD","doc_type":"pod"},{**copy.deepcopy(DOC),"id":"DB","tenant_id":TB,"load_id":"LB"}]
 monkeypatch.setattr(server,"db",db); server.app.dependency_overrides.clear()
 async def actor(x_test_user:str=Header("ops")):
  record=await db.users.find_one({"id":USERS.get(x_test_user,USERS["ops"])["id"]})
  if not record: raise HTTPException(401,"User unavailable")
  record.pop("_id",None); return record
 server.app.dependency_overrides[server.get_current_user]=actor
 yield TestClient(server.app),db
 server.app.dependency_overrides.clear()
def h(user): return {"X-Test-User":user}

def test_create_controls_server_fields_and_excludes_id(api):
 c,db=api; r=c.post("/api/loads/L1/rate-confirmation-extractions",json={"document_id":"DOC1","source":"manual","extracted_fields":{"total_rate":1200}},headers=h("ops")); assert r.status_code==201
 body=r.json(); assert body["id"].startswith("rcx_") and body["tenant_id"]==TA and body["created_by"]=="U-ops" and body["status"]=="draft" and body["version"]==body["revision"]==1 and "_id" not in body
 assert db.events.index("audit_events.insert")<db.events.index("rate_confirmation_extractions.insert")
@pytest.mark.parametrize("extra",[{"tenant_id":TA},{"created_by":"x"},{"status":"accepted"},{"version":9},{"accepted_snapshot":{}},{"created_at":"x"}])
def test_create_rejects_protected_fields(api,extra):
 c,_=api; assert c.post("/api/loads/L1/rate-confirmation-extractions",json={"document_id":"DOC1",**extra},headers=h("ops")).status_code==422
@pytest.mark.parametrize("source",["system","future_ocr","future_ai"])
def test_inactive_sources_and_manual_confidence_rejected(api,source):
 c,_=api; assert c.post("/api/loads/L1/rate-confirmation-extractions",json={"document_id":"DOC1","source":source},headers=h("owner")).status_code==422
 assert c.post("/api/loads/L1/rate-confirmation-extractions",json={"document_id":"DOC1","extraction_confidence":{"total_rate":.9}},headers=h("ops")).status_code==422
def test_create_relationships_tenancy_and_structured_role(api):
 c,_=api
 assert c.post("/api/loads/L1/rate-confirmation-extractions",json={"document_id":"POD"},headers=h("ops")).status_code==409
 assert c.post("/api/loads/L1/rate-confirmation-extractions",json={"document_id":"DOC2"},headers=h("ops")).status_code==409
 assert c.post("/api/loads/LB/rate-confirmation-extractions",json={"document_id":"DB"},headers=h("owner")).status_code==404
 assert c.post("/api/loads/L1/rate-confirmation-extractions",json={"document_id":"DB"},headers=h("ops")).status_code==404
 assert c.post("/api/loads/L1/rate-confirmation-extractions",json={"document_id":"DOC1","source":"structured_import"},headers=h("ops")).status_code==403
 assert c.post("/api/loads/L1/rate-confirmation-extractions",json={"document_id":"DOC1","source":"structured_import","extraction_confidence":{"total_rate":.8}},headers=h("owner")).status_code==201
def test_lists_reads_limits_sorting_and_tenantless(api):
 c,db=api; db.rate_confirmation_extractions.docs=[extraction(),{**extraction(tenant=TB),"id":"rcx_b"},{**extraction(),"id":"rcx_new","created_at":"2026-02-01"}]
 a=c.get("/api/rate-confirmation-extractions",headers=h("ops")); assert [x["id"] for x in a.json()]==["rcx_new","rcx_one"] and all("_id" not in x for x in a.json())
 assert [x["id"] for x in c.get("/api/rate-confirmation-extractions",headers=h("foreign")).json()]==["rcx_b"]
 assert c.get("/api/rate-confirmation-extractions/rcx_b",headers=h("owner")).status_code==404
 assert c.get("/api/loads/L1/rate-confirmation-extractions",headers=h("foreign")).status_code==404
 assert c.get("/api/documents/DOC1/rate-confirmation-extractions",headers=h("foreign")).status_code==404
 assert c.get("/api/rate-confirmation-extractions?limit=201",headers=h("ops")).status_code==422
 assert c.get("/api/rate-confirmation-extractions",headers=h("tenantless")).status_code==403
def test_update_protection_race_audit_and_payload(api):
 c,db=api; db.rate_confirmation_extractions.docs=[extraction()]
 assert c.put("/api/rate-confirmation-extractions/rcx_one",json={"notes":"ok","extracted_fields":{"total_rate":1300}},headers=h("ops")).status_code==200
 payload=db.rate_confirmation_extractions.update_calls[-1][1]["$set"]; assert set(payload)=={"notes","extracted_fields","updated_at","updated_by","version"}
 for body in ({"status":"accepted"},{"source":"structured_import"},{"version":4},{"extraction_confidence":{"total_rate":.5}}): assert c.put("/api/rate-confirmation-extractions/rcx_one",json=body,headers=h("ops")).status_code==422
 db.rate_confirmation_extractions.docs[0]["status"]="accepted"; assert c.put("/api/rate-confirmation-extractions/rcx_one",json={"notes":"x"},headers=h("ops")).status_code==409
 db.rate_confirmation_extractions.docs[0]["status"]="draft"; db.rate_confirmation_extractions.matched_count_override=0; assert c.put("/api/rate-confirmation-extractions/rcx_one",json={"notes":"race"},headers=h("ops")).status_code==409
 db.rate_confirmation_extractions.docs[0]["tenant_id"]=TB; assert c.put("/api/rate-confirmation-extractions/rcx_one",json={"notes":"x"},headers=h("owner")).status_code==404
def test_audit_start_failure_blocks_update(api):
 c,db=api; db.rate_confirmation_extractions.docs=[extraction()]; db.audit_events.fail_insert=True
 assert c.put("/api/rate-confirmation-extractions/rcx_one",json={"notes":"blocked"},headers=h("ops")).status_code==503 and not db.rate_confirmation_extractions.update_calls
def test_confidence_source_role_and_bounds(api):
 c,db=api; db.rate_confirmation_extractions.docs=[extraction(source="structured_import")]
 assert c.put("/api/rate-confirmation-extractions/rcx_one/confidence",json={"extraction_confidence":{"total_rate":.8}},headers=h("ops")).status_code==403
 assert c.put("/api/rate-confirmation-extractions/rcx_one/confidence",json={"extraction_confidence":{"total_rate":.8}},headers=h("owner")).status_code==200
 for value in (-.1,1.1,"NaN","Infinity"): assert c.put("/api/rate-confirmation-extractions/rcx_one/confidence",json={"extraction_confidence":{"total_rate":value}},headers=h("owner")).status_code==422
 db.rate_confirmation_extractions.docs[0]["source"]="manual"; assert c.put("/api/rate-confirmation-extractions/rcx_one/confidence",json={"extraction_confidence":{"total_rate":.8}},headers=h("owner")).status_code==409
def test_lifecycle_guards_and_cross_tenant(api):
 c,db=api; db.rate_confirmation_extractions.docs=[extraction()]
 assert c.post("/api/rate-confirmation-extractions/rcx_one/accept",json={},headers=h("owner")).status_code==409
 assert c.post("/api/rate-confirmation-extractions/rcx_one/submit",json={},headers=h("ops")).status_code==200
 db.rate_confirmation_extractions.docs[0]["status"]="rejected"; assert c.post("/api/rate-confirmation-extractions/rcx_one/return-to-review",json={},headers=h("ops")).status_code==200
 db.rate_confirmation_extractions.docs[0]["status"]="accepted"; assert c.post("/api/rate-confirmation-extractions/rcx_one/supersede",json={"reason":"replacement"},headers=h("owner")).status_code==200
 db.rate_confirmation_extractions.docs[0]["tenant_id"]=TB
 for path in ("compare","submit","accept","return-to-review"): assert c.post(f"/api/rate-confirmation-extractions/rcx_one/{path}",json={},headers=h("owner")).status_code==404
def test_resolution_roles_waiver_and_corrected_validation(api):
 c,db=api; e=extraction("discrepancies_found",fields={**FIELDS,"total_rate":1000,"commodity":"Other"}); result=compare_rate_confirmation(e["extracted_fields"],LOAD,"fixed"); e["comparison_result"]=result; e["discrepancies"]=result["discrepancies"]; db.rate_confirmation_extractions.docs=[e]
 rate=next(d for d in e["discrepancies"] if d["type"]=="total_rate_mismatch"); commodity=next(d for d in e["discrepancies"] if d["type"]=="commodity_mismatch")
 base=f"/api/rate-confirmation-extractions/rcx_one/discrepancies/"
 assert c.put(base+rate["id"],json={"resolution":"corrected_load","decision":"corrected_value","corrected_value":1300,"reason":""},headers=h("finance")).status_code==200
 assert c.put(base+commodity["id"],json={"resolution":"accepted_as_document","decision":"use_document_value","reason":""},headers=h("finance")).status_code==403
 assert c.put(base+commodity["id"],json={"resolution":"accepted_as_document","decision":"use_document_value","reason":""},headers=h("ops")).status_code==200
 assert c.put(base+rate["id"],json={"resolution":"waived","decision":"keep_load_value","reason":""},headers=h("owner")).status_code==422
 assert c.put(base+rate["id"],json={"resolution":"waived","decision":"keep_load_value","reason":"owner waiver"},headers=h("finance")).status_code==403
 assert c.put(base+rate["id"],json={"resolution":"corrected_load","decision":"corrected_value","corrected_value":-1,"reason":""},headers=h("owner")).status_code==422
 assert c.put(base+rate["id"],json={"resolution":"corrected_load","decision":"corrected_value","corrected_value":"not-number","reason":""},headers=h("owner")).status_code==422
 assert c.put(base+rate["id"],json={"resolution":"accepted_as_load","decision":"keep_load_value","reason":"","canonical_field":"evil"},headers=h("owner")).status_code==422
 assert c.put(base+rate["id"],json={"resolution":"accepted_as_load","decision":"keep_load_value","reason":""},headers=h("viewer")).status_code==403
def test_unresolved_blocking_prevents_acceptance(api):
 c,db=api; e=extraction("discrepancies_found",fields={**FIELDS,"total_rate":1000}); r=compare_rate_confirmation(e["extracted_fields"],LOAD,"fixed"); e["discrepancies"]=r["discrepancies"]; e["comparison_result"]=r; db.rate_confirmation_extractions.docs=[e]
 assert c.post("/api/rate-confirmation-extractions/rcx_one/accept",json={},headers=h("owner")).status_code==409 and not db.loads.update_calls and db.rate_confirmation_extractions.docs[0]["status"]!="accepted"
def approved_passport():
 return {"id":"lps_1","tenant_id":TA,"load_id":"L1","version":4,"status":"pickup_authorized","approved_at":"now","approved_by":"U-owner","approved_version":4,"pickup_authorization":{"id":"pua","status":"active"},"blocking_reasons":[],"checkpoints":[{"type":x,"status":"pass","blocking":True} for x in ("load_details","rate_confirmation","broker_identity","shipper_identity","profitability","appointment_feasibility","pickup_instructions")],"load_snapshot":copy.deepcopy(LOAD),"assignment_snapshot":{},"profitability_snapshot":{},"required_checkpoint_types":[]}
def cleared_party():
 return {"id":"PVC1","tenant_id":TA,"load_id":"L1","version":2,"status":"cleared","reviews":{x:{"domain":x,"result":"pass"} for x in ("broker_identity","shipper_identity","contact_validation","pickup_instructions","fraud_risk")},"blocking_reasons":[]}
def resolved_rate_extraction():
 e=extraction("discrepancies_found",fields={**FIELDS,"total_rate":1500}); r=compare_rate_confirmation(e["extracted_fields"],LOAD,"fixed"); d=next(x for x in r["discrepancies"] if x["type"]=="total_rate_mismatch"); e["discrepancies"]=r["discrepancies"]; e["comparison_result"]=r; e["reviewer_resolutions"]=[{"discrepancy_id":d["id"],"discrepancy_type":d["type"],"resolution":"accepted_as_document","decision":"use_document_value","corrected_value":None,"reason":"","resolved_at":"now","resolved_by":"U-owner","resolved_by_role":"owner"}]; return e
def test_lost_passport_race_prevents_load_and_acceptance(api):
 c,db=api; db.rate_confirmation_extractions.docs=[resolved_rate_extraction()]; db.load_passports.docs=[approved_passport()]; db.load_passports.matched_count_override=0
 assert c.post("/api/rate-confirmation-extractions/rcx_one/accept",json={},headers=h("owner")).status_code==409 and not db.loads.update_calls and not db.rate_confirmation_extractions.update_calls
def test_successful_material_acceptance_and_conservative_load_failure(api):
 c,db=api; db.rate_confirmation_extractions.docs=[resolved_rate_extraction()]; db.load_passports.docs=[approved_passport()]; r=c.post("/api/rate-confirmation-extractions/rcx_one/accept",json={},headers=h("owner")); assert r.status_code==200
 p=db.load_passports.docs[0]; assert p["status"]=="review_pending" and p["approved_at"] is None and p["pickup_authorization"]["status"]=="revoked" and db.loads.docs[0]["rate"]==1500 and db.loads.docs[0]["rpm"]==3 and r.json()["accepted_snapshot"]
 assert next(x for x in p["checkpoints"] if x["type"]=="rate_confirmation")["status"]=="pass"
 # Re-run from clean state with a canonical write failure: invalidation remains conservative.
 db.rate_confirmation_extractions.docs=[resolved_rate_extraction()]; db.load_passports.docs=[approved_passport()]; db.loads.docs[0]=copy.deepcopy(LOAD); db.loads.fail_update=True
 failed=c.post("/api/rate-confirmation-extractions/rcx_one/accept",json={},headers=h("owner")); assert failed.status_code==500 and db.load_passports.docs[0]["status"]=="review_pending" and db.load_passports.docs[0]["pickup_authorization"]["status"]=="revoked" and db.rate_confirmation_extractions.docs[0]["status"]!="accepted"
def test_accept_audit_start_failure_changes_nothing(api):
 c,db=api; db.rate_confirmation_extractions.docs=[resolved_rate_extraction()]; db.load_passports.docs=[approved_passport()]; before=(copy.deepcopy(db.loads.docs),copy.deepcopy(db.load_passports.docs),copy.deepcopy(db.rate_confirmation_extractions.docs)); db.audit_events.fail_insert=True
 assert c.post("/api/rate-confirmation-extractions/rcx_one/accept",json={},headers=h("owner")).status_code==503 and before==(db.loads.docs,db.load_passports.docs,db.rate_confirmation_extractions.docs)
def test_extraction_acceptance_race_after_load_write_stays_invalidated(api):
 c,db=api; db.rate_confirmation_extractions.docs=[resolved_rate_extraction()]; db.load_passports.docs=[approved_passport()]; db.rate_confirmation_extractions.matched_count_override=0
 r=c.post("/api/rate-confirmation-extractions/rcx_one/accept",json={},headers=h("owner")); assert r.status_code==409
 assert db.loads.docs[0]["rate"]==1500 and db.load_passports.docs[0]["status"]=="review_pending" and db.load_passports.docs[0]["pickup_authorization"]["status"]=="revoked" and db.rate_confirmation_extractions.docs[0]["status"]!="accepted"

def test_supersession_consumes_passport_and_party_impacts(api):
 c,db=api;db.party_verification_cases=Collection("party_verification_cases",db.events);db.party_verification_cases.docs=[cleared_party()]
 e=extraction("accepted");e["accepted_snapshot"]={"extracted_fields":{"total_rate":5000}};db.rate_confirmation_extractions.docs=[e];db.load_passports.docs=[approved_passport()]
 r=c.post("/api/rate-confirmation-extractions/rcx_one/supersede",json={"reason":"same-dollar replacement evidence"},headers=h("owner"))
 assert r.status_code==200 and r.json()["status"]=="superseded"
 assert db.load_passports.docs[0]["status"]=="review_pending"
 assert db.party_verification_cases.docs[0]["status"]=="review_pending"
 assert db.events.index("load_passports.update")<db.events.index("party_verification_cases.update")<db.events.index("rate_confirmation_extractions.update")

@pytest.mark.parametrize("target",["load_passports","party_verification_cases"])
def test_supersession_target_race_blocks_parent(api,target):
 c,db=api;db.party_verification_cases=Collection("party_verification_cases",db.events);db.party_verification_cases.docs=[cleared_party()]
 db.rate_confirmation_extractions.docs=[extraction("accepted")];db.load_passports.docs=[approved_passport()];getattr(db,target).matched_count_override=0
 assert c.post("/api/rate-confirmation-extractions/rcx_one/supersede",json={"reason":"replacement"},headers=h("owner")).status_code==409
 assert db.rate_confirmation_extractions.docs[0]["status"]=="accepted"

def test_supersession_parent_failure_preserves_conservative_impacts(api):
 c,db=api;db.party_verification_cases=Collection("party_verification_cases",db.events);db.party_verification_cases.docs=[cleared_party()]
 db.rate_confirmation_extractions.docs=[extraction("accepted")];db.load_passports.docs=[approved_passport()];db.rate_confirmation_extractions.fail_update=True
 assert c.post("/api/rate-confirmation-extractions/rcx_one/supersede",json={"reason":"replacement"},headers=h("owner")).status_code==500
 assert db.load_passports.docs[0]["status"]=="review_pending" and db.party_verification_cases.docs[0]["status"]=="review_pending"
 assert db.rate_confirmation_extractions.docs[0]["status"]=="accepted"

def test_supersession_audit_start_failure_has_no_downstream_effect(api):
 c,db=api;db.party_verification_cases=Collection("party_verification_cases",db.events);db.party_verification_cases.docs=[cleared_party()]
 db.rate_confirmation_extractions.docs=[extraction("accepted")];db.load_passports.docs=[approved_passport()];before=(copy.deepcopy(db.load_passports.docs),copy.deepcopy(db.party_verification_cases.docs));db.audit_events.fail_insert=True
 assert c.post("/api/rate-confirmation-extractions/rcx_one/supersede",json={"reason":"replacement"},headers=h("owner")).status_code==503
 assert before==(db.load_passports.docs,db.party_verification_cases.docs) and db.rate_confirmation_extractions.docs[0]["status"]=="accepted"
