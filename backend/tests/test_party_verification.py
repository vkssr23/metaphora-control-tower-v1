"""Isolated deterministic Phase 1C unit and schema tests; no network or database."""
import copy
import pytest
from pydantic import ValidationError
from app.domain.party_verification import evaluate, norm, phone, snapshots, is_insurance_document, qualified_insurance_documents, material_effects, build_case_preinvalidation, build_passport_preinvalidation, assert_mutable, rate_confirmation_required
from app.schemas.party_verification import CaseCreate, ReviewUpdate, ReviewSource, ReviewResult, FindingUpdate

LOAD={"id":"L1","broker":"Broker One","customer":"Shipper One","pickup_address":"1 Main St","pickup_city":"Erie","pickup_state":"PA","pickup_zip":"16501","pickup_appt":"2026-08-07T10:00:00+00:00","rate_con_number":"PU-1","equipment_type":"Dry Van","commodity":"Paper"}
PASSPORT={"id":"lps_1","version":2}
RATE={"accepted_snapshot":{"extracted_fields":{"broker_name":"Broker One","broker_mc":"MC123","broker_contact_email":"ops@gmail.com","broker_contact_phone":"(814) 555-1212","pickup_address":"1 MAIN ST","pickup_number":"PU-1","equipment_type":"dry van","commodity":"paper"}}}
TENANT={"name":"Carrier One","usdot":"123456","mc":"MC999"}
DOC={"id":"D1","filename":"insurance.pdf","doc_type":"insurance","uploaded_at":"2026-08-01","uploaded_by":"U1","url":"https://secret.example/file?token=no"}

def case(documents=None):
    b,s,c,i,cv,p=snapshots(LOAD,PASSPORT,RATE,[DOC] if documents is None else documents,TENANT)
    return {"broker_snapshot":b,"shipper_snapshot":s,"carrier_snapshot":c,"insurance_evidence_snapshot":i,"contact_validation_snapshot":cv,"pickup_instruction_snapshot":p,"findings":[]}

def test_normalization_is_explicit_and_deterministic():
    assert norm("  ONE   Main ST ")=="one main st"
    assert phone("+1 (814) 555-1212")=="18145551212"

def test_snapshots_are_bounded_and_exclude_document_url_and_contents():
    c=case(); assert c["insurance_evidence_snapshot"][0]["document_id"]=="D1"
    assert "url" not in c["insurance_evidence_snapshot"][0] and "content" not in c["insurance_evidence_snapshot"][0]

def test_same_input_has_same_score_and_signals_and_score_is_bounded():
    c=case(); first=evaluate(copy.deepcopy(c),LOAD,RATE)[1]; second=evaluate(copy.deepcopy(c),LOAD,RATE)[1]
    for key in ("risk_level","risk_score","signal_count","blocking_signal_count","critical_signal_count","signals","blocking_reasons","recommended_action","notice"): assert first[key]==second[key]
    assert 0<=first["risk_score"]<=100 and "not a fraud probability" in first["notice"]

def test_missing_insurance_is_blocking_but_free_domain_is_informational():
    findings,risk=evaluate(case([]),LOAD,RATE)
    missing=next(x for x in findings if x["type"]=="insurance_document_missing"); free=next(x for x in findings if x["type"]=="conflicting_contact_information")
    assert missing["blocking"] is True and free["blocking"] is False and risk["blocking_signal_count"]>=1

def test_pickup_mismatches_are_deterministic_and_blocking():
    changed=copy.deepcopy(RATE); changed["accepted_snapshot"]["extracted_fields"]["pickup_address"]="99 Other Rd"
    findings,_=evaluate(case(),LOAD,changed); assert next(x for x in findings if x["type"]=="pickup_address_mismatch")["blocking"] is True

@pytest.mark.parametrize("source",[ReviewSource.SYSTEM,ReviewSource.FUTURE_FMCSA,ReviewSource.FUTURE_INSURANCE,ReviewSource.FUTURE_IDENTITY,ReviewSource.FUTURE_FRAUD])
def test_clients_cannot_submit_reserved_or_future_sources(source):
    with pytest.raises(ValidationError): ReviewUpdate(result=ReviewResult.MATCH,source=source)

def test_manual_review_is_accepted_and_waiver_requires_reason():
    assert ReviewUpdate(result="match",source="manual").source.value=="manual"
    with pytest.raises(ValidationError): ReviewUpdate(result="waived",source="manual")

def test_protected_case_fields_and_unknown_fields_are_rejected():
    for payload in ({"tenant_id":"foreign"},{"status":"cleared"},{"version":9},{"created_by":"attacker"},{"findings":[]},{"risk_summary":{}},{"unknown":1}):
        with pytest.raises(ValidationError): CaseCreate.model_validate(payload)

def test_finding_update_is_strict_and_bounded():
    assert FindingUpdate(resolution="confirmed_match",reason="internally matched").resolution.value=="confirmed_match"
    with pytest.raises(ValidationError): FindingUpdate(resolution="confirmed_match",reason="ok",type="arbitrary")

@pytest.mark.parametrize("kind",["bol","pod","invoice","rate_con","other","lumper","scale"])
def test_only_explicit_insurance_type_qualifies(kind):
    assert not is_insurance_document({"doc_type":kind})
    assert qualified_insurance_documents([{"doc_type":kind}])==[]

def test_insurance_classifier_and_stated_expiry_finding():
    expired={**DOC,"stated_expiration_date":"2020-01-01"}; assert is_insurance_document(expired)
    findings,_=evaluate(case([expired]),LOAD,RATE); assert any(x["type"]=="insurance_document_expired_by_stated_date" and x["blocking"] for x in findings)

def test_material_mapping_and_invalidation_plans_are_deterministic():
    effects=material_effects(["equipment_type","commodity","insurance_evidence"])
    assert effects["domains"]==sorted(effects["domains"]) and "pickup_instructions" in effects["domains"] and effects["revoke_pickup"]
    c={"id":"pvc_1","status":"cleared","version":4,"reviews":{d:{"domain":d,"result":"match"} for d in ("pickup_instructions","fraud_risk")}}
    plan=build_case_preinvalidation(c,["equipment_type"],"U1","now"); assert plan["required"] and plan["update"]["version"]==5 and plan["update"]["status"]=="review_pending"
    p={"id":"lps_1","status":"approved","version":7,"checkpoints":[{"type":"pickup_instructions","status":"pass"},{"type":"driver_eligibility","status":"pass"}],"pickup_authorization":{"status":"active"}}
    pp=build_passport_preinvalidation(p,effects,"U1","now"); assert pp["update"]["version"]==8 and pp["update"]["pickup_authorization"]["status"]=="revoked" and pp["update"]["checkpoints"][1]["status"]=="pass"

def test_status_guards_and_rate_requirement():
    assert not assert_mutable("cleared","evaluate") and assert_mutable("draft","evaluate") and not assert_mutable("expired","evidence")
    assert rate_confirmation_required([{"doc_type":"rate_con"}]) and not rate_confirmation_required([{"doc_type":"insurance"}])

# --- Phase 6: Metaphora Verify broker-authority integration -----------------

def test_verify_result_none_adds_no_verify_findings():
    findings,_=evaluate(case(),LOAD,RATE)
    assert not any(f["type"].startswith("verify_broker_") for f in findings)

def test_verify_unavailable_is_informational_and_non_blocking():
    findings,_=evaluate(case(),LOAD,RATE,{"status":"unavailable"})
    f=next(x for x in findings if x["type"]=="verify_broker_check_unavailable")
    assert f["severity"]=="info" and f["blocking"] is False

def test_verify_mc_not_found_is_high_and_blocking():
    findings,_=evaluate(case(),LOAD,RATE,{"status":"not_found"})
    f=next(x for x in findings if x["type"]=="verify_broker_mc_not_found")
    assert f["severity"]=="high" and f["blocking"] is True

def test_verify_authority_and_bond_gaps_are_blocking():
    vr={"status":"ok","broker_authority_status":"I","bond_insurance_required":"Y",
        "bond_insurance_on_file":"N","risk_level":"Yellow","flags":[]}
    findings,_=evaluate(case(),LOAD,RATE,vr)
    types={f["type"] for f in findings}
    assert {"verify_broker_authority_inactive","verify_broker_bond_not_on_file","verify_broker_risk_yellow"}<=types
    for t in ("verify_broker_authority_inactive","verify_broker_bond_not_on_file"):
        assert next(f for f in findings if f["type"]==t)["blocking"] is True
    assert next(f for f in findings if f["type"]=="verify_broker_risk_yellow")["blocking"] is False

def test_verify_shared_contact_flags_map_to_severity():
    revoked_vr={"status":"ok","broker_authority_status":"A","bond_insurance_required":"N",
                "bond_insurance_on_file":"N","risk_level":"Red",
                "flags":[{"code":"SHARED_CONTACT_REVOKED_ENTITY","message":"Shares phone with a revoked entity."}]}
    findings,risk=evaluate(case(),LOAD,RATE,revoked_vr)
    f=next(x for x in findings if x["type"]=="verify_broker_shared_contact_revoked_entity")
    assert f["severity"]=="critical" and f["blocking"] is True and risk["risk_level"]=="critical"

    other_vr={**revoked_vr,"flags":[{"code":"SHARED_CONTACT_OTHER_ENTITY","message":"Shares an address with another entity."}]}
    findings2,_=evaluate(case(),LOAD,RATE,other_vr)
    f2=next(x for x in findings2 if x["type"]=="verify_broker_shared_contact_other_entity")
    assert f2["severity"]=="warning" and f2["blocking"] is False

def test_verify_findings_carry_forward_resolution_like_internal_findings():
    c=case()
    c["findings"]=[{"type":"verify_broker_authority_inactive","domain":"broker_identity","status":"waived",
                     "resolution":"accepted_internal_value","resolution_reason":"ok for now",
                     "resolved_at":"2026-01-01","resolved_by":"u1","resolved_by_role":"admin",
                     "evidence_document_ids":[]}]
    vr={"status":"ok","broker_authority_status":"I","bond_insurance_required":"N",
        "bond_insurance_on_file":"N","risk_level":"Green","flags":[]}
    findings,_=evaluate(c,LOAD,RATE,vr)
    carried=next(x for x in findings if x["type"]=="verify_broker_authority_inactive")
    assert carried["status"]=="waived" and carried["resolution"]=="accepted_internal_value"

def test_same_verify_result_input_has_same_score_and_signals():
    vr={"status":"ok","broker_authority_status":"I","bond_insurance_required":"N",
        "bond_insurance_on_file":"N","risk_level":"Yellow","flags":[]}
    first=evaluate(copy.deepcopy(case()),LOAD,RATE,copy.deepcopy(vr))[1]
    second=evaluate(copy.deepcopy(case()),LOAD,RATE,copy.deepcopy(vr))[1]
    for key in ("risk_level","risk_score","signal_count","blocking_signal_count","critical_signal_count","signals","blocking_reasons"):
        assert first[key]==second[key]
