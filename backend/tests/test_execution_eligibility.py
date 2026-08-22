from datetime import date,timedelta
from app.domain.execution_eligibility import *

def test_expiration_policy():
    today=date(2026,1,1)
    assert expiration("",today)=="missing" and expiration("2025-12-31",today)=="expired"
    assert expiration("2026-01-31",today)=="expires_soon" and expiration("2026-02-01",today)=="current"
def test_administrative_policies():
    assert administrative_result("mvr","Clear")=="pass" and administrative_result("mvr","Review")=="warning" and administrative_result("mvr","Expired")=="expired"
    assert administrative_result("clearinghouse","Pending")=="warning" and administrative_result("clearinghouse","Issue")=="fail"
    assert administrative_result("employment","Pending")=="warning"
    assert administrative_result("maintenance","Good")=="pass" and administrative_result("maintenance","Bad")=="fail"
def test_operational_policies():
    assert driver_operational("Available")=="pass" and driver_operational("Inactive")=="fail"
    assert truck_operational("Idle")=="pass" and truck_operational("Maintenance")=="fail"
def test_equipment_never_silently_accepts_unknown():
    assert equipment_compatibility("Reefer","Dry Van")=="fail"
    assert equipment_compatibility("mystery","mystery")=="warning"
    assert equipment_compatibility("Dry Van","Dry Van")=="pass"
def test_appointments_and_hos():
    assert appointment_result("","")=="insufficient_data"
    assert appointment_result("2026-01-02T00:00:00+00:00","2026-01-01T00:00:00+00:00")=="fail"
    assert appointment_result("2026-01-01T00:00:00+00:00","2026-01-02T00:00:00+00:00")=="pass"
    assert hos_result({})=="insufficient_data" and hos_result({"reviewed_for_load":True,"available_drive_hours":4,"planned_drive_hours":5})=="fail"
def test_verdict_composition():
    assert verdict([{"result":"pass"}])=="eligible"
    assert verdict([{"result":"warning"}])=="review_required"
    assert verdict([{"result":"fail"}])=="blocked"
def test_deterministic_same_input_and_missing_assignments_block():
    load={"id":"L","driver_id":None,"truck_id":None,"equipment_type":"Power Only"}; passport={"id":"P","load_id":"L","version":1}; case={"checks":[],"trailer_snapshot":{},"hos_readiness_snapshot":{}}
    a=evaluate(load,None,None,case,passport,None,None); b=evaluate(load,None,None,case,passport,None,None)
    assert [(x["type"],x["result"]) for x in a["checks"]]==[(x["type"],x["result"]) for x in b["checks"]]
    assert a["verdict"]=="blocked" and "driver_assignment" in a["blocking_reasons"]
def test_passport_sync_only_four_checkpoints_and_revokes_authorization():
    p={"version":2,"checkpoints":[{"type":x,"status":"pending"} for x in (*EXECUTION_CHECKPOINTS,"profitability")],"pickup_authorization":{"status":"active"}}
    out=passport_sync(p,{},False,"U","now")
    assert out["version"]==3 and out["pickup_authorization"]["status"]=="revoked"
    assert next(x for x in out["checkpoints"] if x["type"]=="profitability")["status"]=="pending"
def test_transition_and_mutation_policy():
    assert "eligible" not in TRANSITIONS["draft"] and TRANSITIONS["eligible"]=={"blocked","expired","revoked"}
    assert "eligible" not in EDITABLE_STATUSES
def test_central_invalidation_planner_is_tenant_and_version_guarded():
    p={"id":"P","tenant_id":"T","version":4,"checkpoints":[{"type":x,"status":"pass"} for x in (*EXECUTION_CHECKPOINTS,"profitability")],"pickup_authorization":{"status":"active","id":"A"}}
    c={"id":"C","tenant_id":"T","passport_id":"P","version":7,"status":"eligible","checks":[{"type":"driver_assignment","result":"pass"}]}
    plan=build_invalidation_plan(c,p,["driver"],"U","now")
    assert plan["eligibility_case_query"]=={"tenant_id":"T","id":"C","status":"eligible","version":7}
    assert plan["passport_query"]=={"tenant_id":"T","id":"P","version":4}
    assert plan["case_next_version"]==8 and plan["passport_next_version"]==5
    assert plan["eligibility_case_update"]["status"]=="review_pending" and plan["eligibility_case_update"]["verdict"]=="pending"
    assert plan["passport_update"]["pickup_authorization"]["status"]=="revoked"
    assert next(x for x in plan["passport_update"]["checkpoints"] if x["type"]=="profitability")["status"]=="pass"
def test_material_mappings_and_refresh_statuses():
    assert {"status","cdl_expiry","medical_expiry","mvr_status","clearinghouse_status","employment_verification"} <= DRIVER_MATERIAL_FIELDS
    assert {"status","maintenance_status","insurance_expiry"} <= TRUCK_MATERIAL_FIELDS
    checks,cps=affected_policy(["driver_assignment","equipment","appointment","party_verification"])
    assert {"driver_assignment","trailer_equipment_compatibility","appointment_feasibility","required_party_clearance"} <= set(checks)
    assert set(cps)==set(EXECUTION_CHECKPOINTS) and "eligible" not in REFRESH_STATUSES
def test_prerequisites_are_policy_mandatory_and_fail_closed():
    load={"id":"L"}; passport={"id":"P","version":3,"rate_confirmation":{"document_id":"D","extraction_id":"R"}}
    missing=evaluate_prerequisites(load,passport,None,None)
    assert missing["party_required"] is True and missing["rate_confirmation_required"] is True
    assert missing["blockers"]==["party_verification_required","accepted_rate_confirmation_required"]
    party={"id":"PV","load_id":"L","passport_id":"P","passport_version":3,"status":"cleared"}; rate={"id":"R","load_id":"L","document_id":"D","status":"accepted"}
    current=evaluate_prerequisites(load,passport,party,rate)
    assert current["party_current"] and current["rate_confirmation_current"] and not current["blockers"]
    assert current==evaluate_prerequisites(load,passport,party,rate)
def test_truck_equipment_result_no_verification_is_insufficient_data():
    # Identical to today's always-insufficient_data behavior when the
    # Metaphora Verify integration isn't configured/attempted at all.
    assert truck_equipment_result(None)==("insufficient_data","")
def test_truck_equipment_result_unavailable_status():
    assert truck_equipment_result({"status":"unavailable"})==("insufficient_data","vehicle_verification_unavailable")
def test_truck_equipment_result_invalid_checksum_fails():
    assert truck_equipment_result({"status":"ok","vin_valid_checksum":False,"plausible_freight_vehicle":False,"risk_level":"Red"})==("fail","vin_check_digit_invalid")
def test_truck_equipment_result_not_freight_appropriate_fails():
    assert truck_equipment_result({"status":"ok","vin_valid_checksum":True,"plausible_freight_vehicle":False,"risk_level":"Red"})==("fail","vehicle_type_not_freight_appropriate")
def test_truck_equipment_result_yellow_is_warning():
    assert truck_equipment_result({"status":"ok","vin_valid_checksum":True,"plausible_freight_vehicle":True,"risk_level":"Yellow"})==("warning","vehicle_decode_partial_or_unusual")
def test_truck_equipment_result_clean_passes():
    assert truck_equipment_result({"status":"ok","vin_valid_checksum":True,"plausible_freight_vehicle":True,"risk_level":"Green"})==("pass","")
def test_evaluate_without_vehicle_verification_arg_is_unaffected():
    # Regression guard: the pre-existing 7-positional-arg call site (see
    # test_deterministic_same_input_and_missing_assignments_block above)
    # must keep behaving exactly as before Phase 7.
    load={"id":"L","driver_id":None,"truck_id":None,"equipment_type":"Power Only"}; passport={"id":"P","load_id":"L","version":1}; case={"checks":[],"trailer_snapshot":{},"hos_readiness_snapshot":{}}
    result=evaluate(load,None,None,case,passport,None,None)
    truck_check=next(c for c in result["checks"] if c["type"]=="truck_equipment_compatibility")
    assert truck_check["result"]=="insufficient_data"
def test_evaluate_with_invalid_vin_blocks_truck_equipment_check():
    load={"id":"L","driver_id":None,"truck_id":"T","equipment_type":"Power Only"}; passport={"id":"P","load_id":"L","version":1}; case={"checks":[],"trailer_snapshot":{},"hos_readiness_snapshot":{}}
    truck={"id":"T","status":"Available"}
    vr={"status":"ok","vin_valid_checksum":False,"plausible_freight_vehicle":False,"risk_level":"Red"}
    result=evaluate(load,None,truck,case,passport,None,None,vr)
    truck_check=next(c for c in result["checks"] if c["type"]=="truck_equipment_compatibility")
    assert truck_check["result"]=="fail" and truck_check["reason"]=="vin_check_digit_invalid"
    assert "vin_check_digit_invalid" in result["blocking_reasons"]
def test_noncurrent_prerequisite_states_fail_closed():
    load={"id":"L"}; passport={"id":"P","version":1,"rate_confirmation":{"document_id":"D"}}
    for state in ("draft","review_pending","findings_open","blocked","expired","revoked"):
        assert not evaluate_prerequisites(load,passport,{"load_id":"L","passport_id":"P","passport_version":1,"status":state},None)["party_current"]
    for state in ("draft","review_pending","discrepancies_found","rejected","superseded"):
        assert not evaluate_prerequisites(load,passport,None,{"load_id":"L","document_id":"D","status":state})["rate_confirmation_current"]
