"""Real FastAPI Phase 1E route tests with fake collections and DB-backed users."""
import copy,pytest
from types import SimpleNamespace
from fastapi import Header,HTTPException
from fastapi.testclient import TestClient
from test_execution_eligibility_routes import FakeDB,Collection,LOAD,USERS,TA,TB,h,server,passport,DRIVER,TRUCK

@pytest.fixture
def api(monkeypatch):
    db=FakeDB()
    for name in ("pickup_release_cases","execution_eligibility_cases","party_verification_cases","rate_confirmation_extractions","tenants","drivers","trucks"): setattr(db,name,Collection(name,db.events))
    load={**copy.deepcopy(LOAD),"driver_id":"D1","truck_id":"T1","customer":"Plant","pickup_address":"1 Main St","pickup_appt":"2026-09-01T10:00:00","rate_con_number":"PU1","equipment_type":"Power Only","commodity":"General","weight":1000}
    p=passport(); p.update({"version":4,"status":"approved","rate_confirmation":{"document_id":"DOC1","extraction_id":"R1"}})
    db.loads.docs=[load,{**load,"id":"LB","tenant_id":TB}]; db.load_passports.docs=[p,{**p,"id":"PB","load_id":"LB","tenant_id":TB}]
    db.drivers.docs=[copy.deepcopy(DRIVER)]; db.trucks.docs=[copy.deepcopy(TRUCK)]; db.documents.docs=[]
    db.rate_confirmation_extractions.docs=[{"id":"R1","tenant_id":TA,"load_id":"L1","version":2,"revision":1,"status":"accepted","document_id":"DOC1","updated_at":"now","accepted_snapshot":{"extracted_fields":{"pickup_name":"Plant","pickup_address":"1 main st","pickup_date":"2026-09-01","pickup_time_start":"10:00","pickup_number":"PU1","equipment_type":"power only","commodity":"general"}}}]
    db.party_verification_cases.docs=[{"id":"V1","tenant_id":TA,"load_id":"L1","passport_id":p["id"],"version":2,"status":"cleared","updated_at":"now","contact_validation_snapshot":{"normalized_email":"jane@example.test"}}]
    db.execution_eligibility_cases.docs=[{"id":"E1","tenant_id":TA,"load_id":"L1","passport_id":p["id"],"passport_version":4,"version":3,"status":"eligible","updated_at":"now","driver_snapshot":{"id":"D1"},"truck_snapshot":{"id":"T1"},"trailer_snapshot":{"identifier":"TRL1"}}]
    monkeypatch.setattr(server,"db",db); server.app.dependency_overrides.clear()
    async def actor(x_test_user:str=Header("ops")):
        record=await db.users.find_one({"id":USERS.get(x_test_user,USERS["ops"])["id"]})
        if not record: raise HTTPException(401,"User unavailable")
        record.pop("_id",None); return record
    server.app.dependency_overrides[server.get_current_user]=actor
    yield TestClient(server.app),db
    server.app.dependency_overrides.clear()
def create(c,user="ops",body=None): return c.post("/api/loads/L1/pickup-release-case",json={} if body is None else body,headers=h(user))
def ready(c):
    cid=create(c).json()["id"]
    assert c.post(f"/api/pickup-release-cases/{cid}/submit",json={},headers=h("ops")).status_code==200
    assert c.post(f"/api/pickup-release-cases/{cid}/evaluate",json={},headers=h("ops")).json()["verdict"]=="release_ready"
    assert c.post(f"/api/pickup-release-cases/{cid}/release-ready",json={},headers=h("owner")).status_code==200
    return cid
def released(c):
    cid=ready(c); assert c.post(f"/api/pickup-release-cases/{cid}/release",json={},headers=h("owner")).status_code==200; return cid
def started_actions(db): return [x["action"] for x in db.audit_events.docs if x.get("phase")=="started"]
def test_create_strict_tenant_owned_unique_and_audit_first(api):
    c,db=api; r=create(c); assert r.status_code==201,r.text; x=r.json(); assert x["id"].startswith("prc_") and x["tenant_id"]==TA and x["version"]==1 and x["status"]=="draft" and "_id" not in x
    assert db.events.index("audit_events.insert")<db.events.index("pickup_release_cases.insert") and create(c).status_code==409
@pytest.mark.parametrize("body",[{"tenant_id":TA},{"status":"released"},{"version":9},{"release_snapshot":{}},{"pickup_authorization_id":"x"},{"custody_events":[]}])
def test_protected_fields_422(api,body): assert create(api[0],body=body).status_code==422
def test_tenant_isolation_and_no_delete(api):
    c,db=api; x=create(c).json(); assert c.get(f"/api/pickup-release-cases/{x['id']}",headers=h("foreign")).status_code==404; assert c.get("/api/pickup-release-cases",headers=h("tenantless")).status_code==403; assert c.delete(f"/api/pickup-release-cases/{x['id']}",headers=h("owner")).status_code==405
def test_submit_evaluate_ready_and_release_order(api):
    c,db=api; cid=create(c).json()["id"]; assert c.post(f"/api/pickup-release-cases/{cid}/release",json={},headers=h("owner")).status_code==409
    assert c.post(f"/api/pickup-release-cases/{cid}/submit",json={},headers=h("ops")).status_code==200
    out=c.post(f"/api/pickup-release-cases/{cid}/evaluate",json={},headers=h("ops")); assert out.status_code==200 and out.json()["verdict"]=="release_ready"
    assert c.post(f"/api/pickup-release-cases/{cid}/release-ready",json={},headers=h("owner")).status_code==200
    mark=len(db.events); released=c.post(f"/api/pickup-release-cases/{cid}/release",json={},headers=h("owner")); assert released.status_code==200,released.text
    body=released.json(); assert body["status"]=="released" and body["custody_state"]=="authorized" and body["pickup_authorization_id"].startswith("pua_")
    segment=db.events[mark:]; assert segment.index("audit_events.insert")<segment.index("load_passports.update")<segment.index("pickup_release_cases.update")
def test_released_immutable_confirm_and_exception(api):
    c,db=api; cid=create(c).json()["id"]; c.post(f"/api/pickup-release-cases/{cid}/submit",json={},headers=h("ops")); c.post(f"/api/pickup-release-cases/{cid}/evaluate",json={},headers=h("ops")); c.post(f"/api/pickup-release-cases/{cid}/release-ready",json={},headers=h("owner")); assert c.post(f"/api/pickup-release-cases/{cid}/release",json={},headers=h("owner")).status_code==200
    for method,path,body in (("put",f"/api/pickup-release-cases/{cid}",{"operational_notes":"x"}),("post",f"/api/pickup-release-cases/{cid}/refresh",{}),("post",f"/api/pickup-release-cases/{cid}/evaluate",{}),("post",f"/api/pickup-release-cases/{cid}/evidence",{"document_ids":["X"]})):
        assert getattr(c,method)(path,json=body,headers=h("owner")).status_code==409
    confirmed=c.post(f"/api/pickup-release-cases/{cid}/confirm-pickup",json={"source":"manual"},headers=h("ops")); assert confirmed.status_code==200 and confirmed.json()["custody_state"]=="pickup_confirmed"
    exc=c.post(f"/api/pickup-release-cases/{cid}/exception",json={"exception_type":"other","reason":"custody review"},headers=h("ops")); assert exc.status_code==200 and exc.json()["status"]=="exception"
def test_audit_start_failure_prevents_create(api):
    c,db=api; db.audit_events.fail_insert=True; assert create(c).status_code==503 and not db.pickup_release_cases.docs
def test_vin_verification_failure_blocks_pickup_release_via_existing_wiring(api):
    # Regression proof for Phase 7's Secure Pickup slice: pickup_release.py
    # itself is unmodified — a VIN check failing on execution-eligibility
    # (which reverts its status away from "eligible") must still correctly
    # block pickup-release through the pre-existing execution_eligibility_
    # not_current wiring, with zero new code in this file.
    c,db=api
    db.execution_eligibility_cases.docs[0]["status"]="review_pending"
    cid=create(c).json()["id"]
    out=c.post(f"/api/pickup-release-cases/{cid}/evaluate",json={},headers=h("ops"))
    assert out.status_code==200
    assert "execution_eligibility_not_current" in out.json()["blocking_reasons"]
    assert out.json()["verdict"]!="release_ready"
@pytest.mark.parametrize("collection",["rate_confirmation_extractions","party_verification_cases","execution_eligibility_cases","load_passports"])
def test_prerequisite_version_drift_blocks_and_refresh_requires_evaluation(api,collection):
    c,db=api; cid=create(c).json()["id"]; getattr(db,collection).docs[0]["version"]+=1
    out=c.post(f"/api/pickup-release-cases/{cid}/evaluate",json={},headers=h("ops")); assert out.status_code==200 and "prerequisite_version_changed" in out.json()["blocking_reasons"]
    refreshed=c.post(f"/api/pickup-release-cases/{cid}/refresh",json={},headers=h("ops")); assert refreshed.status_code==200 and refreshed.json()["verdict"]=="pending" and refreshed.json()["checklist_items"]==[]
def test_final_passport_race_never_releases_case(api):
    c,db=api; cid=ready(c); db.load_passports.matched_count_override=0
    assert c.post(f"/api/pickup-release-cases/{cid}/release",json={},headers=h("owner")).status_code==409 and db.pickup_release_cases.docs[0]["status"]=="release_ready"
def test_final_case_race_confirms_cleanup(api):
    c,db=api; cid=ready(c); db.pickup_release_cases.matched_count_override=0
    out=c.post(f"/api/pickup-release-cases/{cid}/release",json={},headers=h("owner")); assert out.status_code==409
    auth=db.load_passports.docs[0]["pickup_authorization"]; assert auth["status"]==auth["state"]=="revoked" and auth["revocation_reason"]=="release_case_finalization_conflict" and db.pickup_release_cases.docs[0]["status"]=="release_ready"
def test_final_case_race_cleanup_conflict_is_503_and_does_not_claim_revocation(api):
    c,db=api; cid=ready(c); db.pickup_release_cases.matched_count_override=0; original=db.load_passports.update_one; calls=0
    async def conflict(query,update,**kwargs):
        nonlocal calls; calls+=1
        if calls==2: db.events.append("load_passports.update"); return SimpleNamespace(matched_count=0,modified_count=0)
        return await original(query,update,**kwargs)
    db.load_passports.update_one=conflict
    out=c.post(f"/api/pickup-release-cases/{cid}/release",json={},headers=h("owner")); assert out.status_code==503 and "reconciliation" in out.json()["detail"].lower()
    assert db.load_passports.docs[0]["pickup_authorization"]["status"]=="active" and db.pickup_release_cases.docs[0]["status"]=="release_ready"
@pytest.mark.parametrize("field",["load_id","passport_id","release_case_id"])
def test_confirmation_rejects_authorization_binding_mismatch(api,field):
    c,db=api; cid=ready(c); assert c.post(f"/api/pickup-release-cases/{cid}/release",json={},headers=h("owner")).status_code==200
    db.load_passports.docs[0]["pickup_authorization"][field]="OTHER"
    out=c.post(f"/api/pickup-release-cases/{cid}/confirm-pickup",json={"source":"manual"},headers=h("ops")); assert out.status_code==409 and out.json()["detail"]=="pickup_authorization_binding_mismatch"
def test_confirmation_consumes_authorization_and_prevents_reuse(api):
    c,db=api; cid=ready(c); c.post(f"/api/pickup-release-cases/{cid}/release",json={},headers=h("owner")); out=c.post(f"/api/pickup-release-cases/{cid}/confirm-pickup",json={"source":"manual"},headers=h("ops")); assert out.status_code==200
    auth=db.load_passports.docs[0]["pickup_authorization"]; assert auth["status"]==auth["state"]=="consumed" and auth["consumed_by"]=="U-ops"
    assert c.post(f"/api/pickup-release-cases/{cid}/confirm-pickup",json={"source":"manual"},headers=h("ops")).status_code==409
@pytest.mark.parametrize("source",["future_driver_app","future_telematics","future_facility","future_identity"])
def test_future_confirmation_sources_rejected(api,source):
    c,db=api; cid=ready(c); c.post(f"/api/pickup-release-cases/{cid}/release",json={},headers=h("owner")); assert c.post(f"/api/pickup-release-cases/{cid}/confirm-pickup",json={"source":source},headers=h("ops")).status_code==422
def test_illegal_upstream_transitions_do_not_invalidate_release(api):
    c,db=api; cid=ready(c); before=db.pickup_release_cases.docs[0]["version"]
    assert c.post("/api/rate-confirmation-extractions/R1/accept",json={},headers=h("owner")).status_code==409
    assert c.post("/api/party-verification-cases/V1/block",json={"reason":"not legal from cleared"},headers=h("owner")).status_code==409
    assert db.pickup_release_cases.docs[0]["status"]=="release_ready" and db.pickup_release_cases.docs[0]["version"]==before
def test_parent_audit_precedes_phase1e_for_supersession(api):
    c,db=api; ready(c); mark=len(db.audit_events.docs); out=c.post("/api/rate-confirmation-extractions/R1/supersede",json={"reason":"new revision"},headers=h("owner")); assert out.status_code==200,out.text
    actions=[x["action"] for x in db.audit_events.docs[mark:] if x.get("phase")=="started"]
    assert actions.index("rate_confirmation.superseded")<actions.index("pickup_release.material_change_invalidated") and db.pickup_release_cases.docs[0]["status"]=="review_pending"
def test_parent_audit_precedes_phase1e_for_party_and_execution_revoke(api):
    c,db=api; ready(c); mark=len(db.audit_events.docs); out=c.post("/api/party-verification-cases/V1/revoke",json={"reason":"clearance withdrawn"},headers=h("owner")); assert out.status_code==200,out.text
    actions=[x["action"] for x in db.audit_events.docs[mark:] if x.get("phase")=="started"]; assert actions.index("party_verification.revoked")<actions.index("pickup_release.material_change_invalidated")
    # Rebuild the Phase 1E case against current records to independently prove Phase 1D ordering.
    db.pickup_release_cases.docs=[]; db.load_passports.docs[0].update({"status":"approved","pickup_authorization":None}); db.party_verification_cases.docs[0].update({"status":"cleared","version":2}); db.execution_eligibility_cases.docs[0].update({"status":"eligible","passport_version":db.load_passports.docs[0]["version"]})
    cid=create(c).json()["id"]; c.post(f"/api/pickup-release-cases/{cid}/submit",json={},headers=h("ops")); c.post(f"/api/pickup-release-cases/{cid}/evaluate",json={},headers=h("ops")); c.post(f"/api/pickup-release-cases/{cid}/release-ready",json={},headers=h("owner")); mark=len(db.audit_events.docs)
    out=c.post("/api/execution-eligibility-cases/E1/revoke",json={"reason":"eligibility withdrawn"},headers=h("owner")); assert out.status_code==200,out.text
    actions=[x["action"] for x in db.audit_events.docs[mark:] if x.get("phase")=="started"]; assert actions.index("execution_eligibility.revoked")<actions.index("pickup_release.material_change_invalidated")
@pytest.mark.parametrize("entity,path,payload",[("driver","/api/drivers/D1",{"mvr_status":"Expired"}),("truck","/api/trucks/T1",{"maintenance_status":"Warn"})])
def test_master_data_change_revokes_phase1e_before_phase1d_and_canonical_write(api,entity,path,payload):
    c,db=api; released(c); mark=len(db.events); out=c.put(path,json=payload,headers=h("owner")); assert out.status_code==200,out.text
    segment=db.events[mark:]; assert segment.index("load_passports.update")<segment.index("pickup_release_cases.update")<segment.index("execution_eligibility_cases.update")<segment.index(f"{entity}s.update")
    assert db.load_passports.docs[0]["pickup_authorization"]["status"]=="revoked" and db.pickup_release_cases.docs[0]["status"]=="exception"
def test_load_assignment_change_parent_audit_then_revokes_and_updates(api):
    c,db=api; released(c); mark=len(db.audit_events.docs); out=c.put("/api/loads/L1",json={"driver_id":None},headers=h("ops")); assert out.status_code==200,out.text
    actions=[x["action"] for x in db.audit_events.docs[mark:] if x.get("phase")=="started"]; assert actions.index("load.updated")<actions.index("pickup_release.material_change_invalidated")
    assert db.pickup_release_cases.docs[0]["status"]=="exception" and db.load_passports.docs[0]["pickup_authorization"]["status"]=="revoked" and db.loads.docs[0]["driver_id"] is None
