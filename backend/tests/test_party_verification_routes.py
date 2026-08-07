"""Principal Phase 1C routes with fake collections and dependency-overridden users."""
import copy, pytest
from fastapi import Header, HTTPException
from fastapi.testclient import TestClient
from test_rate_confirmation_routes import FakeDB, Collection, LOAD, DOC, USERS, TA, TB, h, extraction, resolved_rate_extraction, approved_passport, server
USERS.setdefault("safety",{"id":"U-safe","email":"safe@example.test","name":"Safety","role":"safety","tenant_id":TA})

def passport(tenant=TA):
    types=("load_details","rate_confirmation","broker_identity","shipper_identity","profitability","driver_eligibility","truck_eligibility","trailer_eligibility","appointment_feasibility","pickup_instructions")
    return {"id":"lps_1","tenant_id":tenant,"load_id":"L1","version":1,"status":"draft","checkpoints":[{"type":x,"status":"pending","blocking":True} for x in types],"blocking_reasons":[],"pickup_authorization":None}

@pytest.fixture
def api(monkeypatch):
    db=FakeDB()
    for name in ("party_verification_cases","tenants"): setattr(db,name,Collection(name,db.events))
    db.loads.docs=[copy.deepcopy(LOAD),{**copy.deepcopy(LOAD),"tenant_id":TB,"id":"LB"}]
    db.documents.docs=[copy.deepcopy(DOC),{"id":"INS1","tenant_id":TA,"load_id":"L1","doc_type":"insurance","filename":"insurance.pdf","uploaded_at":"now","uploaded_by":"U-ops"},{**copy.deepcopy(DOC),"tenant_id":TB,"id":"DB","load_id":"LB"}]
    db.load_passports.docs=[passport(),{**passport(TB),"id":"lps_b","load_id":"LB"}]
    accepted=extraction(status="accepted"); accepted["accepted_snapshot"]={"extracted_fields":copy.deepcopy(accepted["extracted_fields"])}; db.rate_confirmation_extractions.docs=[accepted]
    db.tenants.docs=[{"id":TA,"name":"Carrier","usdot":"123","mc":"MC1"},{"id":TB,"name":"Foreign"}]
    monkeypatch.setattr(server,"db",db); server.app.dependency_overrides.clear()
    async def actor(x_test_user:str=Header("ops")):
        record=await db.users.find_one({"id":USERS.get(x_test_user,USERS["ops"])["id"]})
        if not record: raise HTTPException(401,"User unavailable")
        record.pop("_id",None); return record
    server.app.dependency_overrides[server.get_current_user]=actor
    yield TestClient(server.app),db
    server.app.dependency_overrides.clear()

def create(client,user="ops"): return client.post("/api/loads/L1/party-verification-case",json={},headers=h(user))

def test_create_is_tenant_owned_audit_first_and_unique(api):
    c,db=api; r=create(c); assert r.status_code==201
    body=r.json(); assert body["id"].startswith("pvc_") and body["tenant_id"]==TA and body["created_by"]=="U-ops" and body["status"]=="draft" and body["version"]==1 and "_id" not in body
    assert db.events.index("audit_events.insert")<db.events.index("party_verification_cases.insert")
    assert create(c).status_code==409

@pytest.mark.parametrize("payload",[{"tenant_id":TA},{"status":"cleared"},{"version":3},{"created_by":"x"},{"risk_summary":{}},{"findings":[]}])
def test_create_rejects_protected_fields(api,payload): assert api[0].post("/api/loads/L1/party-verification-case",json=payload,headers=h("ops")).status_code==422

def test_cross_tenant_and_viewer_are_blocked(api):
    c,db=api; assert c.post("/api/loads/LB/party-verification-case",json={},headers=h("owner")).status_code==404
    assert create(c,"viewer").status_code==403; body=create(c).json(); assert c.get(f"/api/party-verification-cases/{body['id']}",headers=h("foreign")).status_code==404

def test_sources_lifecycle_roles_and_audit_failure(api):
    c,db=api; item=create(c).json(); cid=item["id"]
    assert c.post(f"/api/party-verification-cases/{cid}/clear",json={},headers=h("owner")).status_code==409
    assert c.post(f"/api/party-verification-cases/{cid}/submit",json={},headers=h("viewer")).status_code==403
    assert c.post(f"/api/party-verification-cases/{cid}/submit",json={},headers=h("ops")).status_code==200
    for source in ("system","future_fmcsa","future_insurance","future_identity","future_fraud_provider"):
        assert c.put(f"/api/party-verification-cases/{cid}/reviews/broker_identity",json={"result":"match","source":source},headers=h("ops")).status_code==422
    assert c.put(f"/api/party-verification-cases/{cid}/reviews/broker_identity",json={"result":"match","source":"manual"},headers=h("ops")).status_code==200
    db.audit_events.fail_insert=True; before=copy.deepcopy(db.party_verification_cases.docs)
    assert c.post(f"/api/party-verification-cases/{cid}/evaluate",json={},headers=h("ops")).status_code==503 and before==db.party_verification_cases.docs

def _reviewable(c,db):
    item=create(c).json(); cid=item["id"]; assert c.post(f"/api/party-verification-cases/{cid}/submit",json={},headers=h("ops")).status_code==200
    current=db.party_verification_cases.docs[0]
    for review in current["reviews"].values(): review.update({"result":"match","source":"manual","reviewed_at":"now","reviewed_by":"U-owner","reviewed_by_role":"owner"})
    return cid

def test_cleared_case_ordinary_mutations_all_return_409_without_changes(api):
    c,db=api; cid=_reviewable(c,db); item=db.party_verification_cases.docs[0]; item["status"]="cleared"; item["findings"]=[{"id":"pvf_1","domain":"broker_identity","type":"broker_name_mismatch","status":"open"}]
    before=copy.deepcopy(item)
    calls=[("post",f"/api/party-verification-cases/{cid}/evaluate",{}),("put",f"/api/party-verification-cases/{cid}/reviews/broker_identity",{"result":"match","source":"manual"}),("put",f"/api/party-verification-cases/{cid}/findings/pvf_1",{"resolution":"confirmed_match","reason":"match"}),("post",f"/api/party-verification-cases/{cid}/evidence",{"document_ids":["INS1"]})]
    for method,path,body in calls: assert getattr(c,method)(path,json=body,headers=h("owner")).status_code==409
    assert db.party_verification_cases.docs[0]==before

def test_unrelated_documents_do_not_qualify_and_missing_insurance_blocks_clear(api):
    c,db=api; db.documents.docs=[copy.deepcopy(DOC)]; cid=_reviewable(c,db)
    r=c.post(f"/api/party-verification-cases/{cid}/clear",json={},headers=h("owner")); assert r.status_code==409 and "insurance_evidence_required" in r.json()["detail"]["blocking_reasons"]
    assert any(x["type"]=="insurance_document_missing" for x in __import__('app.domain.party_verification',fromlist=['evaluate']).evaluate(db.party_verification_cases.docs[0],LOAD,db.rate_confirmation_extractions.docs[0])[0])

def test_clear_requires_current_accepted_rate_confirmation(api):
    c,db=api; cid=_reviewable(c,db); db.rate_confirmation_extractions.docs[0]["status"]="draft"
    r=c.post(f"/api/party-verification-cases/{cid}/clear",json={},headers=h("owner")); assert r.status_code==409 and "accepted_rate_confirmation_required" in r.json()["detail"]["blocking_reasons"]

def test_clear_orders_passport_before_case_and_increments_version(api):
    c,db=api; cid=_reviewable(c,db); start=len(db.events); r=c.post(f"/api/party-verification-cases/{cid}/clear",json={},headers=h("owner")); assert r.status_code==200
    segment=db.events[start:]; assert segment.index("load_passports.update")<segment.index("party_verification_cases.update")
    assert db.load_passports.docs[0]["version"]==2 and r.json()["status"]=="cleared" and r.json()["passport_version"]==2
    assert next(x for x in db.load_passports.docs[0]["checkpoints"] if x["type"]=="driver_eligibility")["status"]=="pending"

def test_passport_race_prevents_case_clear(api):
    c,db=api; cid=_reviewable(c,db); db.load_passports.matched_count_override=0; before=len(db.party_verification_cases.update_calls)
    assert c.post(f"/api/party-verification-cases/{cid}/clear",json={},headers=h("owner")).status_code==409
    assert len(db.party_verification_cases.update_calls)==before and db.party_verification_cases.docs[0]["status"]=="review_pending"

def test_case_race_after_passport_sync_never_falsely_clears_or_restores(api):
    c,db=api; cid=_reviewable(c,db); db.party_verification_cases.matched_count_override=0
    assert c.post(f"/api/party-verification-cases/{cid}/clear",json={},headers=h("owner")).status_code==409
    assert db.party_verification_cases.docs[0]["status"]=="review_pending" and db.load_passports.docs[0]["version"]==3 and db.load_passports.docs[0]["status"]=="review_pending"

@pytest.mark.parametrize("field,value",[("equipment_type","Reefer"),("commodity","Steel"),("weight",41000),("pickup_address","99 Changed Rd")])
def test_direct_material_load_changes_preinvalidate_case_and_passport(api,field,value):
    c,db=api; item=create(c).json(); db.party_verification_cases.docs[0]["status"]="cleared"; p=db.load_passports.docs[0]; p.update({"status":"approved","approved_at":"now","approved_by":"U-owner","approved_version":1,"pickup_authorization":{"status":"active","id":"pua_1"}})
    assert c.put("/api/loads/L1",json={field:value},headers=h("ops")).status_code==200
    assert db.party_verification_cases.docs[0]["status"]=="review_pending" and db.party_verification_cases.docs[0]["cleared_at"] is None
    assert p["status"]=="review_pending" and p["version"]==2 and p["pickup_authorization"]["status"]=="revoked"

def test_material_case_race_prevents_load_write(api):
    c,db=api; create(c); db.party_verification_cases.docs[0]["status"]="cleared"; db.party_verification_cases.matched_count_override=0; before=copy.deepcopy(db.loads.docs[0])
    assert c.put("/api/loads/L1",json={"equipment_type":"Reefer"},headers=h("ops")).status_code==409 and db.loads.docs[0]==before

def test_qualified_document_invalidates_but_unrelated_document_does_not(api):
    c,db=api; create(c); case_doc=db.party_verification_cases.docs[0]; case_doc["status"]="cleared"; p=db.load_passports.docs[0]; p["status"]="approved"
    unrelated={"load_id":"L1","doc_type":"other","filename":"note.pdf","url":"mock://note.pdf"}
    assert c.post("/api/documents",json=unrelated,headers=h("ops")).status_code==200 and case_doc["status"]=="cleared"
    insurance={"load_id":"L1","doc_type":"insurance","filename":"coi.pdf","url":"mock://coi.pdf","stated_expiration_date":"2027-01-01","named_insured":"Carrier"}
    assert c.post("/api/documents",json=insurance,headers=h("ops")).status_code==200
    assert case_doc["status"]=="review_pending" and p["status"]=="review_pending" and p["version"]==2

def test_document_invalidation_race_prevents_insert(api):
    c,db=api; create(c); db.party_verification_cases.docs[0]["status"]="cleared"; db.party_verification_cases.matched_count_override=0; before=len(db.documents.docs)
    body={"load_id":"L1","doc_type":"insurance","filename":"coi.pdf","url":"mock://coi.pdf"}
    assert c.post("/api/documents",json=body,headers=h("ops")).status_code==409 and len(db.documents.docs)==before

def test_document_failure_after_invalidation_stays_conservative(api):
    c,db=api; create(c); db.party_verification_cases.docs[0]["status"]="cleared"; db.load_passports.docs[0]["status"]="approved"; db.documents.fail_insert=True
    body={"load_id":"L1","doc_type":"insurance","filename":"coi.pdf","url":"mock://coi.pdf"}
    assert c.post("/api/documents",json=body,headers=h("ops")).status_code==500
    assert db.party_verification_cases.docs[0]["status"]=="review_pending" and db.load_passports.docs[0]["status"]=="review_pending"

def test_rate_confirmation_acceptance_preinvalidates_cleared_case(api):
    c,db=api; db.load_passports.docs=[approved_passport()]; create(c); db.party_verification_cases.docs[0]["status"]="cleared"; db.party_verification_cases.docs[0]["passport_version"]=4; db.rate_confirmation_extractions.docs=[resolved_rate_extraction()]
    r=c.post("/api/rate-confirmation-extractions/rcx_one/accept",json={},headers=h("owner")); assert r.status_code==200
    assert db.party_verification_cases.docs[0]["status"]=="review_pending" and db.load_passports.docs[0]["status"]=="review_pending" and db.load_passports.docs[0]["pickup_authorization"]["status"]=="revoked"

def test_rate_confirmation_case_race_prevents_acceptance(api):
    c,db=api; db.load_passports.docs=[approved_passport()]; create(c); db.party_verification_cases.docs[0]["status"]="cleared"; db.rate_confirmation_extractions.docs=[resolved_rate_extraction()]; db.party_verification_cases.matched_count_override=0
    assert c.post("/api/rate-confirmation-extractions/rcx_one/accept",json={},headers=h("owner")).status_code==409
    assert not db.loads.update_calls and not db.rate_confirmation_extractions.update_calls

def test_incomplete_domain_and_passport_drift_block_clear(api):
    c,db=api; item=create(c).json(); cid=item["id"]; assert c.post(f"/api/party-verification-cases/{cid}/submit",json={},headers=h("ops")).status_code==200
    r=c.post(f"/api/party-verification-cases/{cid}/clear",json={},headers=h("owner")); assert r.status_code==409 and "required_review_domain_incomplete" in r.json()["detail"]["blocking_reasons"]
    for review in db.party_verification_cases.docs[0]["reviews"].values(): review["result"]="match"
    db.load_passports.docs[0]["version"]=2
    r=c.post(f"/api/party-verification-cases/{cid}/clear",json={},headers=h("owner")); assert r.status_code==409 and "passport_version_changed" in r.json()["detail"]["blocking_reasons"]

def test_accepted_extraction_must_reference_same_load_rate_document(api):
    c,db=api; cid=_reviewable(c,db); db.rate_confirmation_extractions.docs[0]["document_id"]="INS1"
    r=c.post(f"/api/party-verification-cases/{cid}/clear",json={},headers=h("owner")); assert r.status_code==409 and "accepted_rate_confirmation_required" in r.json()["detail"]["blocking_reasons"]

def test_domain_role_matrix_and_waiver_controls(api):
    c,db=api; cid=create(c).json()["id"]; base=f"/api/party-verification-cases/{cid}/reviews/"
    assert c.put(base+"broker_identity",json={"result":"match","source":"manual"},headers=h("ops")).status_code==200
    assert c.put(base+"carrier_authority",json={"result":"match","source":"manual"},headers=h("ops")).status_code==403
    assert c.put(base+"carrier_authority",json={"result":"match","source":"manual"},headers=h("safety")).status_code==200
    assert c.put(base+"contact_validation",json={"result":"match","source":"manual"},headers=h("finance")).status_code==200
    assert c.put(base+"broker_identity",json={"result":"match","source":"manual"},headers=h("viewer")).status_code==403
    assert c.put(base+"insurance_evidence",json={"result":"waived","source":"manual","reason":""},headers=h("owner")).status_code==422
    assert c.put(base+"insurance_evidence",json={"result":"waived","source":"manual","reason":"bounded administrative waiver"},headers=h("safety")).status_code==403
    assert c.put(base+"insurance_evidence",json={"result":"waived","source":"manual","reason":"bounded administrative waiver"},headers=h("owner")).status_code==200

def test_lists_are_tenant_scoped_bounded_sorted_and_no_delete(api):
    c,db=api; first=create(c).json(); db.party_verification_cases.docs.append({**copy.deepcopy(first),"id":"pvc_new","updated_at":"9999","_id":"private"}); db.party_verification_cases.docs.append({**copy.deepcopy(first),"id":"pvc_foreign","tenant_id":TB,"updated_at":"9999"})
    rows=c.get("/api/party-verification-cases?limit=1",headers=h("ops")); assert rows.status_code==200 and [x["id"] for x in rows.json()]==["pvc_new"] and "_id" not in rows.json()[0]
    assert c.get("/api/party-verification-cases?limit=201",headers=h("ops")).status_code==422
    assert c.get("/api/party-verification-cases",headers=h("tenantless")).status_code==403
    assert c.delete(f"/api/party-verification-cases/{first['id']}",headers=h("owner")).status_code==405

def test_responses_contain_no_external_verification_claims(api):
    c,db=api; body=create(c).json(); text=str(body).lower()
    for forbidden in ("fmcsa verified","insurance verified","policy active","identity verified","fraud cleared","document authentic"): assert forbidden not in text

def test_load_failure_after_material_invalidation_stays_conservative(api):
    c,db=api; create(c); db.party_verification_cases.docs[0]["status"]="cleared"; p=db.load_passports.docs[0]; p.update({"status":"approved","pickup_authorization":{"status":"active"}}); db.loads.fail_update=True
    assert c.put("/api/loads/L1",json={"commodity":"Changed"},headers=h("ops")).status_code==500
    assert db.party_verification_cases.docs[0]["status"]=="review_pending" and p["status"]=="review_pending" and p["pickup_authorization"]["status"]=="revoked"
