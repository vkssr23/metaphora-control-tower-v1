"""Real FastAPI Phase 1D route tests using fake collections and DB-backed users."""
import copy,pytest
from fastapi import Header,HTTPException
from fastapi.testclient import TestClient
from test_rate_confirmation_routes import FakeDB,Collection,LOAD,DOC,USERS,TA,TB,h,server,resolved_rate_extraction
from test_party_verification_routes import passport

USERS.setdefault("safety",{"id":"U-safe","email":"safe@example.test","name":"Safety","role":"safety","tenant_id":TA})
DRIVER={"id":"D1","tenant_id":TA,"name":"Driver","status":"Available","cdl_expiry":"2030-01-01","medical_expiry":"2030-01-01","mvr_status":"Clear","clearinghouse_status":"Clear","employment_verification":"Complete"}
TRUCK={"id":"T1","tenant_id":TA,"truck_number":"101","status":"Available","maintenance_status":"Good","insurance_expiry":"2030-01-01"}
@pytest.fixture
def api(monkeypatch):
    db=FakeDB()
    for name in ("execution_eligibility_cases","party_verification_cases","tenants","drivers","trucks"): setattr(db,name,Collection(name,db.events))
    load={**copy.deepcopy(LOAD),"driver_id":"D1","truck_id":"T1","equipment_type":"Power Only","pickup_appt":"2026-09-01T10:00:00+00:00","delivery_appt":"2026-09-02T10:00:00+00:00","commodity":"General","weight":1000}
    db.loads.docs=[load,{**load,"id":"LB","tenant_id":TB}]; db.drivers.docs=[copy.deepcopy(DRIVER),{**DRIVER,"id":"DB","tenant_id":TB}]; db.trucks.docs=[copy.deepcopy(TRUCK),{**TRUCK,"id":"TB","tenant_id":TB}]
    db.documents.docs=[copy.deepcopy(DOC)]; db.load_passports.docs=[passport(),{**passport(TB),"id":"lps_b","load_id":"LB"}]; db.rate_confirmation_extractions.docs=[]; db.party_verification_cases.docs=[]
    monkeypatch.setattr(server,"db",db); server.app.dependency_overrides.clear()
    async def actor(x_test_user:str=Header("ops")):
        record=await db.users.find_one({"id":USERS.get(x_test_user,USERS["ops"])["id"]})
        if not record: raise HTTPException(401,"User unavailable")
        record.pop("_id",None); return record
    server.app.dependency_overrides[server.get_current_user]=actor
    yield TestClient(server.app),db
    server.app.dependency_overrides.clear()
def create(c,user="ops",body=None): return c.post("/api/loads/L1/execution-eligibility-case",json=body or {},headers=h(user))
def make_eligible(c,db):
    item=create(c).json(); case=db.execution_eligibility_cases.docs[0]; case.update({"status":"eligible","verdict":"eligible","approved_at":"now","approved_by":"U-owner","driver_snapshot":{"id":"D1"},"truck_snapshot":{"id":"T1"}})
    p=db.load_passports.docs[0]; p.update({"status":"pickup_authorized","pickup_authorization":{"id":"pua","status":"active"}})
    for cp in p["checkpoints"]: cp["status"]="pass"
    return item["id"]
def test_create_is_strict_tenant_owned_audit_first_and_unique(api):
    c,db=api; r=create(c); assert r.status_code==201
    x=r.json(); assert x["id"].startswith("eec_") and x["tenant_id"]==TA and x["created_by"]=="U-ops" and x["version"]==1 and x["status"]=="draft" and "_id" not in x
    assert db.events.index("audit_events.insert")<db.events.index("execution_eligibility_cases.insert") and create(c).status_code==409
@pytest.mark.parametrize("payload",[{"tenant_id":TA},{"status":"eligible"},{"verdict":"eligible"},{"version":9},{"checks":[]},{"driver_snapshot":{}}])
def test_protected_fields_rejected(api,payload): assert create(api[0],body=payload).status_code==422
def test_tenant_isolation_roles_lists_and_no_delete(api):
    c,db=api; assert c.post("/api/loads/LB/execution-eligibility-case",json={},headers=h("owner")).status_code==404
    x=create(c).json(); assert c.get(f"/api/execution-eligibility-cases/{x['id']}",headers=h("foreign")).status_code==404
    assert c.get("/api/execution-eligibility-cases",headers=h("tenantless")).status_code==403
    assert c.delete(f"/api/execution-eligibility-cases/{x['id']}",headers=h("owner")).status_code==405
def test_source_restrictions_waiver_and_domain_roles(api):
    c,db=api; x=create(c).json(); url=f"/api/execution-eligibility-cases/{x['id']}/checks/appointment_feasibility"
    assert c.put(url,json={"result":"pass","source":"manual"},headers=h("ops")).status_code==200
    for source in ("system","future_fmcsa","future_dmv","future_clearinghouse","future_eld","future_telematics","future_insurance","future_maintenance"):
        assert c.put(url,json={"result":"pass","source":source},headers=h("ops")).status_code==422
    safety=f"/api/execution-eligibility-cases/{x['id']}/checks/cdl_administrative_status"
    assert c.put(safety,json={"result":"pass"},headers=h("ops")).status_code==403
    assert c.put(safety,json={"result":"waived","reason":"bounded reason"},headers=h("safety")).status_code==403
def test_workflow_evaluation_and_eligible_mutation_guard(api):
    c,db=api; x=create(c).json(); cid=x["id"]
    assert c.post(f"/api/execution-eligibility-cases/{cid}/eligible",json={},headers=h("owner")).status_code==409
    assert c.post(f"/api/execution-eligibility-cases/{cid}/submit",json={},headers=h("ops")).status_code==200
    r=c.post(f"/api/execution-eligibility-cases/{cid}/evaluate",json={},headers=h("safety")); assert r.status_code==200 and r.json()["verdict"] in {"review_required","blocked"}
    assert c.post(f"/api/execution-eligibility-cases/{cid}/eligible",json={},headers=h("owner")).status_code==409
def test_missing_assignments_and_bad_maintenance_block(api):
    c,db=api; db.loads.docs[0]["driver_id"]=None; db.trucks.docs[0]["maintenance_status"]="Bad"; cid=create(c).json()["id"]
    r=c.post(f"/api/execution-eligibility-cases/{cid}/evaluate",json={},headers=h("safety")); assert r.status_code==200
    assert "driver_assignment" in r.json()["blocking_reasons"] and "truck_maintenance_condition" in r.json()["blocking_reasons"]
def test_audit_start_failure_prevents_create(api):
    c,db=api; db.audit_events.fail_insert=True; assert create(c).status_code==503 and not db.execution_eligibility_cases.docs
def test_unknown_fields_and_external_claims(api):
    c,db=api; x=create(c).json(); assert c.post(f"/api/execution-eligibility-cases/{x['id']}/submit",json={"actor":"x"},headers=h("ops")).status_code==422
    text=str(x).lower()
    for phrase in ("fmcsa verified","dmv verified","eld compliant","insurance verified","telematics verified"): assert phrase not in text
def test_refresh_findings_hos_and_eligible_immutability(api):
    c,db=api; cid=create(c).json()["id"]
    refreshed=c.post(f"/api/execution-eligibility-cases/{cid}/refresh",json={},headers=h("safety")); assert refreshed.status_code==200 and refreshed.json()["driver_snapshot"]["id"]=="D1"
    assert c.put(f"/api/execution-eligibility-cases/{cid}/hos-readiness",json={"source":"future_eld","available_drive_hours":8,"required_trip_hours":7},headers=h("ops")).status_code==422
    assert c.put(f"/api/execution-eligibility-cases/{cid}/hos-readiness",json={"available_drive_hours":8,"required_trip_hours":7},headers=h("ops")).status_code==200
    case=db.execution_eligibility_cases.docs[0]; case["status"]="review_pending"; case["findings"]=[{"id":"eef_x","type":"mvr_administrative_status","severity":"warning","status":"open"}]
    assert c.put(f"/api/execution-eligibility-cases/{cid}/findings/eef_x",json={"resolution":"resolved","reason":"review completed"},headers=h("ops")).status_code==403
    r=c.put(f"/api/execution-eligibility-cases/{cid}/findings/eef_x",json={"resolution":"resolved","reason":"review completed"},headers=h("safety")); assert r.status_code==200 and r.json()["findings"][0]["resolved_by"]=="U-safe"
    case["status"]="eligible"
    calls=[("put",f"/api/execution-eligibility-cases/{cid}",{"operational_notes":"x"}),("post",f"/api/execution-eligibility-cases/{cid}/refresh",{}),("post",f"/api/execution-eligibility-cases/{cid}/evaluate",{}),("put",f"/api/execution-eligibility-cases/{cid}/checks/appointment_feasibility",{"result":"pass"}),("put",f"/api/execution-eligibility-cases/{cid}/findings/eef_x",{"resolution":"resolved","reason":"again"}),("post",f"/api/execution-eligibility-cases/{cid}/evidence",{"document_ids":["DOC1"]}),("put",f"/api/execution-eligibility-cases/{cid}/hos-readiness",{"available_drive_hours":8,"required_trip_hours":7})]
    for method,path,body in calls: assert getattr(c,method)(path,json=body,headers=h("owner")).status_code==409
def test_driver_truck_and_load_changes_preinvalidate_before_canonical_write(api):
    c,db=api; cid=make_eligible(c,db); start=len(db.events)
    assert c.put("/api/drivers/D1",json={"cdl_expiry":"2025-01-01"},headers=h("safety")).status_code==200
    assert db.execution_eligibility_cases.docs[0]["status"]=="review_pending" and db.load_passports.docs[0]["pickup_authorization"]["status"]=="revoked"
    segment=db.events[start:]; assert segment.index("load_passports.update")<segment.index("execution_eligibility_cases.update")<segment.index("drivers.update")
    db.execution_eligibility_cases.docs=[]; db.load_passports.docs=[passport()]; cid=make_eligible(c,db); start=len(db.events)
    assert c.put("/api/trucks/T1",json={"maintenance_status":"Warn"},headers=h("safety")).status_code==200
    segment=db.events[start:]; assert segment.index("load_passports.update")<segment.index("execution_eligibility_cases.update")<segment.index("trucks.update")
    db.execution_eligibility_cases.docs=[]; db.load_passports.docs=[passport()]; cid=make_eligible(c,db); start=len(db.events)
    assert c.put("/api/loads/L1",json={"driver_id":None},headers=h("ops")).status_code==200
    segment=db.events[start:]; assert segment.index("load_passports.update")<segment.index("execution_eligibility_cases.update")<segment.index("loads.update")
def test_invalidation_races_prevent_driver_and_load_canonical_writes(api):
    c,db=api; make_eligible(c,db); db.execution_eligibility_cases.matched_count_override=0
    assert c.put("/api/drivers/D1",json={"mvr_status":"Expired"},headers=h("safety")).status_code==409 and not db.drivers.update_calls
    assert db.load_passports.docs[0]["pickup_authorization"]["status"]=="revoked" and db.execution_eligibility_cases.docs[0]["status"]=="eligible"
    db.execution_eligibility_cases.matched_count_override=None; db.execution_eligibility_cases.docs=[]; db.load_passports.docs=[passport()]; make_eligible(c,db); db.load_passports.matched_count_override=0
    assert c.put("/api/loads/L1",json={"equipment_type":"Reefer"},headers=h("ops")).status_code==409 and not db.loads.update_calls
    assert db.execution_eligibility_cases.docs[0]["status"]=="eligible" and db.load_passports.docs[0]["pickup_authorization"]["status"]=="active"
def test_canonical_failure_never_restores_eligibility(api):
    c,db=api; make_eligible(c,db); db.drivers.fail_update=True
    assert c.put("/api/drivers/D1",json={"medical_expiry":"2025-01-01"},headers=h("safety")).status_code==500
    assert db.execution_eligibility_cases.docs[0]["status"]=="review_pending" and db.load_passports.docs[0]["pickup_authorization"]["status"]=="revoked"
def test_rate_supersession_and_party_revocation_invalidate_first(api):
    c,db=api; make_eligible(c,db); db.rate_confirmation_extractions.docs=[{"id":"R1","tenant_id":TA,"load_id":"L1","status":"accepted","version":1,"updated_at":"now"}]
    assert c.post("/api/rate-confirmation-extractions/R1/supersede",json={"reason":"replacement"},headers=h("owner")).status_code==200
    assert db.execution_eligibility_cases.docs[0]["status"]=="review_pending"
    db.execution_eligibility_cases.docs=[]; db.load_passports.docs=[passport()]; make_eligible(c,db); db.party_verification_cases.docs=[{"id":"P1","tenant_id":TA,"load_id":"L1","status":"cleared","version":1,"passport_id":"lps_1","passport_version":1,"blocking_reasons":[],"findings":[]}]
    assert c.post("/api/party-verification-cases/P1/revoke",json={"reason":"clearance revoked"},headers=h("owner")).status_code==200
    assert db.execution_eligibility_cases.docs[0]["status"]=="review_pending" and db.party_verification_cases.docs[0]["status"]=="revoked"
def test_eligible_revoke_is_passport_first_and_race_safe(api):
    c,db=api; cid=make_eligible(c,db); start=len(db.events)
    assert c.post(f"/api/execution-eligibility-cases/{cid}/revoke",json={"reason":"unsafe change"},headers=h("owner")).status_code==200
    segment=db.events[start:]; assert segment.index("load_passports.update")<segment.index("execution_eligibility_cases.update") and db.load_passports.docs[0]["pickup_authorization"]["status"]=="revoked"
    db.execution_eligibility_cases.docs=[]; db.load_passports.docs=[passport()]; cid=make_eligible(c,db); db.load_passports.docs[0]["assignment_snapshot"]={"trailer_identifier":"TRL-1"}; db.load_passports.matched_count_override=0
    assert c.post(f"/api/execution-eligibility-cases/{cid}/expire",json={},headers=h("owner")).status_code==409 and db.execution_eligibility_cases.docs[0]["status"]=="eligible"
def valid_final_case(c,db):
    cid=create(c).json()["id"]; case=db.execution_eligibility_cases.docs[0]; p=db.load_passports.docs[0]
    p["rate_confirmation"]={"document_id":"DOC1","extraction_id":"R1"}
    case.update({"status":"review_pending","passport_version":p["version"],"hos_readiness_snapshot":{"reviewed_for_load":True,"available_drive_hours":10,"required_trip_hours":8},"checks":[{"type":x,"result":"waived","source":"manual","reason":"bounded owner waiver","checked_by":"U-owner"} for x in ("truck_equipment_compatibility","load_weight_fit","commodity_equipment_fit")]})
    db.party_verification_cases.docs=[{"id":"PV1","tenant_id":TA,"load_id":"L1","passport_id":p["id"],"passport_version":p["version"],"status":"cleared","updated_at":"now","version":1}]
    db.rate_confirmation_extractions.docs=[{"id":"R1","tenant_id":TA,"load_id":"L1","document_id":"DOC1","status":"accepted","updated_at":"now","version":1}]
    return cid
def test_hard_prerequisites_fail_closed_at_final_route(api):
    c,db=api; cid=create(c).json()["id"]; db.execution_eligibility_cases.docs[0]["status"]="review_pending"
    r=c.post(f"/api/execution-eligibility-cases/{cid}/eligible",json={},headers=h("owner")); assert r.status_code==409 and "party_verification_required" in r.json()["detail"]["blocking_reasons"] and "accepted_rate_confirmation_required" in r.json()["detail"]["blocking_reasons"]
    for state in ("draft","revoked"):
        db.party_verification_cases.docs=[{"id":"PV","tenant_id":TA,"load_id":"L1","passport_id":"lps_1","passport_version":1,"status":state,"updated_at":"now"}]
        assert c.post(f"/api/execution-eligibility-cases/{cid}/eligible",json={},headers=h("owner")).status_code==409
    db.party_verification_cases.docs=[]; db.rate_confirmation_extractions.docs=[{"id":"R","tenant_id":TA,"load_id":"L1","document_id":"DOC1","status":"superseded","updated_at":"now"}]
    assert c.post(f"/api/execution-eligibility-cases/{cid}/eligible",json={},headers=h("owner")).status_code==409
def test_successful_final_eligibility_and_both_races(api):
    c,db=api; cid=valid_final_case(c,db); start=len(db.events); r=c.post(f"/api/execution-eligibility-cases/{cid}/eligible",json={},headers=h("owner")); assert r.status_code==200
    body=r.json(); assert body["status"]==body["verdict"]=="eligible" and body["passport_version"]==2 and "_id" not in body
    segment=db.events[start:]; assert segment.index("audit_events.insert")<segment.index("load_passports.update")<segment.index("execution_eligibility_cases.update")
    for kind in ("driver_eligibility","truck_eligibility","trailer_eligibility","appointment_feasibility"): assert next(x for x in db.load_passports.docs[0]["checkpoints"] if x["type"]==kind)["status"]=="pass"
    db.execution_eligibility_cases.docs=[]; db.load_passports.docs=[passport()]; cid=valid_final_case(c,db); db.load_passports.matched_count_override=0; before=len(db.execution_eligibility_cases.update_calls)
    assert c.post(f"/api/execution-eligibility-cases/{cid}/eligible",json={},headers=h("owner")).status_code==409 and len(db.execution_eligibility_cases.update_calls)==before and db.execution_eligibility_cases.docs[0]["status"]=="review_pending"
    db.execution_eligibility_cases.docs=[]; db.load_passports.docs=[passport()]; db.load_passports.matched_count_override=None; cid=valid_final_case(c,db); db.execution_eligibility_cases.matched_count_override=0
    assert c.post(f"/api/execution-eligibility-cases/{cid}/eligible",json={},headers=h("owner")).status_code==409 and db.execution_eligibility_cases.docs[0]["status"]=="review_pending" and db.load_passports.docs[0]["version"]==2
def test_master_data_discovery_fails_closed_above_ceiling(api):
    c,db=api; base=make_eligible(c,db); original=copy.deepcopy(db.execution_eligibility_cases.docs[0]); db.execution_eligibility_cases.docs=[{**copy.deepcopy(original),"id":f"E{i}","passport_id":f"P{i}"} for i in range(101)]
    db.load_passports.docs=[{**passport(),"id":f"P{i}","pickup_authorization":{"id":f"A{i}","status":"active"}} for i in range(101)]
    assert c.put("/api/drivers/D1",json={"status":"Inactive"},headers=h("safety")).status_code==409 and not db.drivers.update_calls
    assert all(x["status"]=="eligible" for x in db.execution_eligibility_cases.docs) and all(x["pickup_authorization"]["status"]=="active" for x in db.load_passports.docs)
def test_trailer_route_is_passport_first_and_race_safe(api):
    c,db=api; cid=make_eligible(c,db); db.load_passports.docs[0]["assignment_snapshot"]={"trailer_identifier":"TRL-1"}; start=len(db.events)
    assert c.put("/api/load-passports/lps_1",json={"trailer_identifier":"TRL-2"},headers=h("ops")).status_code==200
    segment=db.events[start:]; assert segment.index("load_passports.update")<segment.index("execution_eligibility_cases.update")<segment.index("load_passports.update",segment.index("execution_eligibility_cases.update")+1)
    assert db.execution_eligibility_cases.docs[0]["status"]=="review_pending" and db.load_passports.docs[0]["assignment_snapshot"]["trailer_identifier"]=="TRL-2"
    db.execution_eligibility_cases.docs=[]; db.load_passports.docs=[passport()]; cid=make_eligible(c,db); db.load_passports.docs[0]["assignment_snapshot"]={"trailer_identifier":"TRL-1"}; db.load_passports.matched_count_override=0
    assert c.put("/api/load-passports/lps_1",json={"trailer_identifier":"RACE"},headers=h("ops")).status_code==409 and db.execution_eligibility_cases.docs[0]["status"]=="eligible"
def test_rate_acceptance_invalidates_before_load_and_acceptance(api):
    c,db=api; make_eligible(c,db); e=resolved_rate_extraction(); e["extracted_fields"].update({"pickup_date":"2026-09-01","delivery_date":"2026-09-02","equipment_type":"Power Only"}); db.rate_confirmation_extractions.docs=[e]; start=len(db.events)
    r=c.post("/api/rate-confirmation-extractions/rcx_one/accept",json={},headers=h("owner")); assert r.status_code==200,r.text
    segment=db.events[start:]; assert segment.index("load_passports.update")<segment.index("execution_eligibility_cases.update")<segment.index("loads.update")<segment.index("rate_confirmation_extractions.update")
    assert db.execution_eligibility_cases.docs[0]["status"]=="review_pending" and db.load_passports.docs[0]["pickup_authorization"]["status"]=="revoked"
def test_party_block_expire_revoke_are_parent_audit_then_passport_then_execution(api):
    c,db=api
    for action,start_status,body,target in (("block","review_pending",{"reason":"blocking concern"},"blocked"),("expire","cleared",{},"expired"),("revoke","cleared",{"reason":"clearance revoked"},"revoked")):
        db.execution_eligibility_cases.docs=[]; db.load_passports.docs=[passport()]; make_eligible(c,db)
        db.party_verification_cases.docs=[{"id":"PV","tenant_id":TA,"load_id":"L1","status":start_status,"version":1,"passport_id":"lps_1","passport_version":1,"blocking_reasons":[],"findings":[]}]
        mark=len(db.events); r=c.post(f"/api/party-verification-cases/PV/{action}",json=body,headers=h("owner")); assert r.status_code==200
        segment=db.events[mark:]; assert segment.index("audit_events.insert")<segment.index("load_passports.update")<segment.index("execution_eligibility_cases.update")<segment.index("party_verification_cases.update")
        assert db.party_verification_cases.docs[0]["status"]==target and db.load_passports.docs[0]["pickup_authorization"]["status"]=="revoked"
def test_party_passport_and_case_races_prevent_final_party_mutation(api):
    c,db=api; make_eligible(c,db); db.party_verification_cases.docs=[{"id":"PV","tenant_id":TA,"load_id":"L1","status":"cleared","version":1,"passport_id":"lps_1","passport_version":1,"blocking_reasons":[],"findings":[]}]; db.load_passports.matched_count_override=0
    assert c.post("/api/party-verification-cases/PV/revoke",json={"reason":"race"},headers=h("owner")).status_code==409 and db.party_verification_cases.docs[0]["status"]=="cleared" and db.execution_eligibility_cases.docs[0]["status"]=="eligible"
    db.load_passports.matched_count_override=None; db.execution_eligibility_cases.matched_count_override=0
    assert c.post("/api/party-verification-cases/PV/revoke",json={"reason":"race"},headers=h("owner")).status_code==409 and db.party_verification_cases.docs[0]["status"]=="cleared" and db.load_passports.docs[0]["pickup_authorization"]["status"]=="revoked"
