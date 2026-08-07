import copy
import pytest
from pydantic import ValidationError
from app.domain.load_passports import REQUIRED_CHECKPOINT_TYPES, build_preinvalidation, calculate_profitability, canonical_hash, evaluate_readiness, material_drift
from app.schemas.passports import CheckpointUpdate, PassportCreate, PassportUpdate, ReasonAction

def load(**overrides):
    value={"id":"L1","customer":"Shipper","broker":"Broker","rate_con_number":"RC1","pickup_address":"A","pickup_appt":"2026-01-01T10:00:00Z","delivery_address":"B","delivery_appt":"2026-01-02T10:00:00Z","miles":500,"rate":2000,"stage":"Assigned","driver_id":"D1","truck_id":"T1"}; value.update(overrides); return value
def passport(status="review_pending"):
    l=load(); return {"id":"lps_x","tenant_id":"ten_"+"a"*32,"load_id":"L1","version":3,"status":status,"approved_version":3 if status=="approved" else None,"blocking_reasons":[],"required_checkpoint_types":list(REQUIRED_CHECKPOINT_TYPES),"load_snapshot":{k:v for k,v in l.items() if k not in {"driver_id","truck_id"}},"assignment_snapshot":{"driver_id":"D1","truck_id":"T1"},"profitability_snapshot":{"estimated_net_profit":100},"checkpoints":[{"type":kind,"status":"pass","blocking":True} for kind in REQUIRED_CHECKPOINT_TYPES],"pickup_authorization":None}

def test_readiness_is_deterministic_and_complete():
    p=passport(); assert evaluate_readiness(p,load())==evaluate_readiness(copy.deepcopy(p),copy.deepcopy(load())); assert evaluate_readiness(p,load())["ready_for_approval"]
@pytest.mark.parametrize("status",["pending","fail","expired"])
def test_blocking_checkpoint_prevents_approval(status):
    p=passport(); p["checkpoints"][0]["status"]=status; result=evaluate_readiness(p,load()); assert not result["ready_for_approval"]; assert p["checkpoints"][0]["type"] in result["unsatisfied_checkpoint_types"]
def test_pass_and_waiver_satisfy_checkpoint():
    p=passport(); p["checkpoints"][0]["status"]="waived"; assert evaluate_readiness(p,load())["ready_for_approval"]
def test_assignment_mismatch_and_missing_assignment_block():
    p=passport(); assert "material_snapshot_drift" in evaluate_readiness(p,load(driver_id="D2"))["blocking_reasons"]; p["assignment_snapshot"]["driver_id"]=None; assert "assignment_incomplete" in evaluate_readiness(p,load(driver_id=None))["blocking_reasons"]
def test_material_drift_detects_rate_lane_party_and_assignment():
    p=passport(); changed=load(rate=2100,pickup_address="C",customer="Other",truck_id="T2"); assert {"rate","pickup_address","customer","truck_id"} <= set(material_drift(p,changed))
def test_missing_profitability_blocks_review_and_approval():
    p=passport(); p["profitability_snapshot"]=None; result=evaluate_readiness(p,load()); assert "profitability_snapshot_missing" in result["blocking_reasons"]
def test_pickup_requires_approved_current_version_and_pre_pickup_stage():
    p=passport("approved"); assert evaluate_readiness(p,load())["ready_for_pickup_authorization"]; p["approved_version"]=2; assert not evaluate_readiness(p,load())["ready_for_pickup_authorization"]; p["approved_version"]=3; assert not evaluate_readiness(p,load(stage="Loaded"))["ready_for_pickup_authorization"]
def test_active_authorization_prevents_duplicate_issue():
    p=passport("approved"); p["pickup_authorization"]={"status":"active"}; assert not evaluate_readiness(p,load())["ready_for_pickup_authorization"]
def test_profitability_matches_existing_formula_components():
    result=calculate_profitability(load(rate=2000,miles=500,tolls=50),{"id":"default","fuel_price":4,"mpg":8,"driver_pay_solo_cpm":.6,"insurance_per_week":500,"rental_per_week":1000,"factoring_fee_pct":2,"default_toll":20}); assert result["fuel_estimate"]==250; assert result["driver_cost"]==300; assert result["total_estimated_cost"]==940; assert result["estimated_net_profit"]==1060
def test_hash_is_canonical_and_sensitive_to_snapshot():
    assert canonical_hash({"a":1,"b":2})==canonical_hash({"b":2,"a":1}); assert canonical_hash({"a":1})!=canonical_hash({"a":2})
@pytest.mark.parametrize("model,payload",[(PassportCreate,{"tenant_id":"x"}),(PassportCreate,{"status":"approved"}),(PassportUpdate,{"version":2}),(ReasonAction,{"reason":""})])
def test_protected_or_invalid_fields_are_rejected(model,payload):
    with pytest.raises(ValidationError): model.model_validate(payload)
def test_checkpoint_waiver_requires_reason_and_external_source_is_rejected():
    with pytest.raises(ValidationError): CheckpointUpdate.model_validate({"status":"waived"})
    with pytest.raises(ValidationError): CheckpointUpdate.model_validate({"status":"pass","source":"future_integration"})
def test_nan_and_infinity_are_not_accepted_by_passport_inputs():
    with pytest.raises(ValidationError): PassportCreate.model_validate({"trailer_identifier":None})
def test_preinvalidation_plan_is_conditional_and_resets_only_affected_checkpoints():
    p=passport("approved"); p["pickup_authorization"]={"id":"pua_x","status":"active"}
    plan=build_preinvalidation(p,["profitability"],"U1","2026-01-01T00:00:00Z")
    assert plan["query"]=={"tenant_id":p["tenant_id"],"id":"lps_x","status":"approved","version":3,"pickup_authorization.status":"active"}
    assert plan["update"]["status"]=="review_pending" and plan["update"]["version"]==4
    assert plan["update"]["pickup_authorization"]["status"]=="revoked"
    reset={c["type"] for c in plan["update"]["checkpoints"] if c["status"]=="pending"}
    assert reset=={"load_details","profitability"}
def test_preinvalidation_skips_inactive_workflow_without_authorization():
    p=passport(); p["status"]="review_pending"; assert not build_preinvalidation(p,["load_details"],"U1","now")["required"]
