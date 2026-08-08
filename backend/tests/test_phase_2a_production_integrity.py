"""Phase 2A is exercised only with deterministic plain records and fake HTTP state."""
import json
import logging
import os
from dataclasses import asdict

os.environ.update({"JWT_SECRET":"isolated-test-only-secret-value-over-32-characters","MONGO_URL":"mongodb://127.0.0.1:1/no-network-test","DB_NAME":"isolated","CORS_ORIGINS":"http://localhost:3000","APP_ENV":"test","ALLOW_SEED_ENDPOINT":"false"})

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.infrastructure.index_manifest import compare_indexes, expected_indexes
from app.domain.in_transit_execution import CURRENT_EXECUTION_SESSION_STATUSES, EXECUTION_SESSION_STATUSES, TERMINAL
from app.observability import RequestContextMiddleware, safe_fields, structured_log
from app.production_integrity import evaluate_environment, evaluate_production_readiness, scan_integrity
from scripts.production_integrity_report import main

TA="ten_"+"a"*32; TB="ten_"+"b"*32
def base(): return {"tenants":[{"id":TA}],"loads":[{"id":"L1","tenant_id":TA,"stage":"Booked"}]}
def codes(report): return [x["code"] for x in report["findings"]]

def test_manifest_is_stable_named_and_classified():
    first=expected_indexes(); second=expected_indexes(); assert first==second
    assert all(x.name and x.priority in {"P0","P1","P2"} and x.fields and x.purpose for x in first)
    assert len({(x.collection,x.name) for x in first})==len(first)
    assert {x.priority for x in first}=={"P0","P1","P2"}

def test_manifest_uniqueness_and_actual_partial_states():
    by={x.name:x for x in expected_indexes()}
    assert by["uq_load_passports_tenant_load"].unique
    assert by["uq_execution_nonterminal_tenant_load"].partial_filter["status"]["$in"]==["active","delivery_arrived","delivery_confirmed","exception","paused","pending_start"]
    assert "released" in by["uq_pickup_active_tenant_load"].partial_filter["status"]["$in"]

def test_index_comparison_is_bounded_and_read_only():
    result=compare_indexes({}); assert result["missing"] and not result["mismatched"]
    observed={"tenants":[{"name":"uq_tenants_id","fields":[["id",1]],"unique":False}]}
    assert compare_indexes(observed)["mismatched"]==[{"collection":"tenants","name":"uq_tenants_id"}]

def test_tenant_missing_malformed_nonexistent_and_valid():
    data=base(); data["documents"]=[{"id":"A"},{"id":"B","tenant_id":"bad"},{"id":"C","tenant_id":TB}]
    report=scan_integrity(data,generated_at="2026-01-01T00:00:00+00:00")
    assert {"TENANT_MISSING","TENANT_ID_MALFORMED","TENANT_REFERENCE_MISSING"}<=set(codes(report))
    assert not any(x["entity_id"]=="L1" and x["code"].startswith("TENANT") for x in report["findings"])

def test_cross_tenant_and_orphan_relationships():
    data=base(); data["tenants"].append({"id":TB}); data["loads"].append({"id":"L2","tenant_id":TB})
    data["documents"]=[{"id":"D1","tenant_id":TA,"load_id":"L2","doc_type":"pod","filename":"p","url":"https://files.test/p"},{"id":"D2","tenant_id":TA,"load_id":"missing","doc_type":"pod","filename":"p","url":"https://files.test/p"}]
    assert {"CROSS_TENANT_REFERENCE","ORPHAN_REFERENCE"}<=set(codes(scan_integrity(data)))

def test_active_collision_uses_partial_filter_but_terminal_history_is_safe():
    data=base(); data["execution_sessions"]=[{"id":"S1","tenant_id":TA,"load_id":"L1","status":"active","version":1},{"id":"S2","tenant_id":TA,"load_id":"L1","status":"exception","version":1},{"id":"S3","tenant_id":TA,"load_id":"L1","status":"completed","version":1}]
    collisions=[x for x in scan_integrity(data)["findings"] if x["code"]=="INDEX_COLLISION" and x["collection"]=="execution_sessions"]
    assert len(collisions)==1 and collisions[0]["count"]==2

def test_every_actual_execution_status_has_explicit_current_or_terminal_classification():
    assert EXECUTION_SESSION_STATUSES=={"pending_start","active","paused","exception","delivery_arrived","delivery_confirmed","completed","cancelled"}
    assert CURRENT_EXECUTION_SESSION_STATUSES==EXECUTION_SESSION_STATUSES-set(TERMINAL)
    predicate=next(x.partial_filter for x in expected_indexes() if x.name=="uq_execution_nonterminal_tenant_load")
    assert set(predicate["status"]["$in"])==set(CURRENT_EXECUTION_SESSION_STATUSES)
    assert not set(predicate["status"]["$in"])&set(TERMINAL)

def test_every_current_execution_state_collides_and_terminal_history_does_not():
    for status in CURRENT_EXECUTION_SESSION_STATUSES:
        data=base(); data["execution_sessions"]=[{"id":"S1","tenant_id":TA,"load_id":"L1","status":status,"version":1},{"id":"S2","tenant_id":TA,"load_id":"L1","status":"active","version":1}]
        assert any(x["code"]=="INDEX_COLLISION" and x["collection"]=="execution_sessions" for x in scan_integrity(data)["findings"]),status
    data=base(); data["execution_sessions"]=[{"id":"S1","tenant_id":TA,"load_id":"L1","status":"completed","version":1},{"id":"S2","tenant_id":TA,"load_id":"L1","status":"cancelled","version":1}]
    assert not any(x["code"]=="INDEX_COLLISION" and x["collection"]=="execution_sessions" for x in scan_integrity(data)["findings"])

def test_duplicate_passport_and_cases_are_critical():
    data=base()
    for collection,status in (("load_passports","approved"),("party_verification_cases","cleared"),("execution_eligibility_cases","eligible"),("pickup_release_cases","released"),("invoice_readiness_cases","ready")):
        data[collection]=[{"id":"1","tenant_id":TA,"load_id":"L1","status":status,"version":1},{"id":"2","tenant_id":TA,"load_id":"L1","status":status,"version":1}]
    collisions=[x for x in scan_integrity(data)["findings"] if x["code"]=="INDEX_COLLISION"]
    assert len(collisions)>=5 and all(x["severity"]=="critical" for x in collisions)

def test_invoice_authority_failures_and_valid_chain():
    data=base(); data["loads"][0]["invoice_status"]="Ready to Invoice"
    data["invoice_readiness_cases"]=[{"id":"R","tenant_id":TA,"load_id":"L1","status":"invoiced","version":1,"invoice_package_id":"P"}]
    report=scan_integrity(data); assert {"INVOICED_READINESS_INVOICE_ID_MISSING","READINESS_PACKAGE_MISSING"}<=set(codes(report))
    data["invoice_readiness_cases"][0].update({"invoice_id":"I","financial_basis_fingerprint":"fp"})
    data["invoice_packages"]=[{"id":"P","tenant_id":TA,"load_id":"L1","readiness_case_id":"R","invoice_id":"I","financial_basis_fingerprint":"fp"}]; data["invoices"]=[{"id":"I","tenant_id":TA,"load_id":"L1","readiness_case_id":"R","package_id":"P","financial_basis_fingerprint":"fp","status":"Ready to Invoice"}]
    assert not ({"INVOICED_READINESS_INVOICE_ID_MISSING","READINESS_PACKAGE_MISSING","LEGACY_INVOICE_AUTHORITY"}&set(codes(scan_integrity(data))))

def test_execution_delivery_consistency():
    data=base(); data["execution_sessions"]=[{"id":"S","tenant_id":TA,"load_id":"L1","status":"completed","execution_state":"delivery_confirmed","custody_state":"delivered","version":1}]
    assert "DELIVERY_LOAD_STATE_DISAGREEMENT" in codes(scan_integrity(data))
    data["loads"][0]["stage"]="Delivered"; assert "DELIVERY_LOAD_STATE_DISAGREEMENT" not in codes(scan_integrity(data))

def test_document_metadata_type_and_mock_blocker():
    data=base(); data["documents"]=[{"id":"D","tenant_id":TA,"load_id":"L1","doc_type":"mystery","url":"mock://p.pdf"}]
    assert {"DOCUMENT_TYPE_UNSUPPORTED","DOCUMENT_METADATA_MISSING","DOCUMENT_STORAGE_SIMULATED"}<=set(codes(scan_integrity(data)))

def test_report_is_deterministic_bounded_and_secret_free():
    data=base(); data["users"]=[{"id":str(i),"password_hash":"secret","tenant_id":"bad"} for i in range(5)]
    a=scan_integrity(data,generated_at="fixed",max_findings=2); b=scan_integrity(data,generated_at="fixed",max_findings=2)
    assert a==b and a["summary"]["truncated"] and len(a["findings"])==2 and "secret" not in json.dumps(a)

def test_environment_secure_missing_and_simulation_blocker():
    secure={"APP_ENV":"production","JWT_SECRET":"x"*32,"MONGO_URL":"mongodb://configured","DB_NAME":"db","CORS_ORIGINS":"https://app.test","FRONTEND_BACKEND_URL":"https://api.test"}
    production=evaluate_environment(secure)
    assert any(x["code"]=="SIMULATED_CAPABILITY_REACHABLE" and x["state"]=="unsafe" for x in production["settings"])
    assert {x["id"] for x in production["simulated_capabilities"] if x["classification"]=="pilot_blocker" and x["reachable"]}>={"routing","weather","road_traffic","telematics_samsara","fuel_truck_stop","mock_document_storage"}
    hidden=evaluate_environment({**secure,"ENABLE_SIMULATED_ROUTING":"false","ENABLE_MOCK_DOCUMENTS":"false"})
    assert any(x["code"]=="SIMULATED_CAPABILITY_REACHABLE" for x in hidden["settings"])
    assert "x"*32 not in json.dumps(evaluate_environment(secure))

def test_readiness_does_not_overclaim_unknown_indexes():
    env=evaluate_environment({"APP_ENV":"production","JWT_SECRET":"x"*32,"MONGO_URL":"x","DB_NAME":"x","CORS_ORIGINS":"https://a.test","FRONTEND_BACKEND_URL":"https://b.test"})
    result=evaluate_production_readiness(env); assert result["status"]=="FAIL" and result["critical_blockers"]>=6 and result["index_verification"]=="UNKNOWN" and result["production_certified"] is False

def test_request_id_generated_honored_bounded_and_returned():
    app=FastAPI(); app.add_middleware(RequestContextMiddleware)
    @app.get("/")
    async def root(): return {"ok":True}
    client=TestClient(app); generated=client.get("/").headers["x-request-id"]
    assert generated.startswith("req_")
    assert client.get("/",headers={"X-Request-ID":"client-123"}).headers["x-request-id"]=="client-123"
    assert client.get("/",headers={"X-Request-ID":"x"*129}).headers["x-request-id"]!="x"*129

def test_structured_logs_redact_sensitive_fields(caplog):
    with caplog.at_level(logging.INFO): structured_log(logging.getLogger("test"),"event",password="bad",authorization="Bearer bad",safe="ok")
    assert "bad" not in caplog.text and "ok" in caplog.text and safe_fields({"jwt":"bad"})["jwt"]=="[REDACTED]"

def test_cli_is_read_only_and_fails_for_critical_blocker(tmp_path,capsys):
    path=tmp_path/"records.json"; path.write_text(json.dumps({"users":[{"id":"U"}]}),encoding="utf-8")
    assert main(["--input",str(path),"--environment","production","--json"])==2
    output=json.loads(capsys.readouterr().out); assert output["read_only"] is True and output["readiness"]["status"]=="FAIL"

def test_email_canonicalization_valid_legacy_duplicate_and_missing():
    data=base(); data["users"]=[{"id":"U1","tenant_id":TA,"email":"valid@example.com"}]
    assert not ({"USER_EMAIL_MISSING","USER_EMAIL_NOT_NORMALIZED","USER_EMAIL_CANONICAL_COLLISION"}&set(codes(scan_integrity(data))))
    data["users"]=[{"id":"U1","tenant_id":TA,"email":" User@Example.COM "},{"id":"U2","tenant_id":TA,"email":"user@example.com"},{"id":"U3","tenant_id":TA,"email":None},{"id":"U4","tenant_id":TA}]
    result=set(codes(scan_integrity(data)))
    assert {"USER_EMAIL_MISSING","USER_EMAIL_NOT_NORMALIZED","USER_EMAIL_CANONICAL_COLLISION","INDEX_NULL_OR_MISSING_KEY","INDEX_COLLISION"}<=result

def test_null_and_missing_unique_components_block_important_p0_indexes():
    cases=(
      ("trucks","uq_trucks_tenant_truck_number",{"status":"Available"}),
      ("load_passports","uq_load_passports_tenant_load",{"status":"approved","version":1}),
      ("party_verification_cases","uq_party_tenant_load",{"status":"cleared","version":1}),
      ("execution_eligibility_cases","uq_eligibility_tenant_load",{"status":"eligible","version":1}),
      ("pickup_release_cases","uq_pickup_active_tenant_load",{"status":"released","version":1}),
      ("invoice_readiness_cases","uq_readiness_active_tenant_load",{"status":"ready","version":1}),
      ("execution_sessions","uq_execution_nonterminal_tenant_load",{"status":"paused","version":1}),
      ("rate_confirmation_extractions","uq_rc_tenant_document_revision",{"load_id":"L1","status":"accepted","version":1}),
      ("invoice_packages","uq_packages_tenant_readiness",{"load_id":"L1"}),
    )
    for collection,index_name,extra in cases:
        data=base(); data[collection]=[{"id":"A","tenant_id":TA,**extra},{"id":"B","tenant_id":TA,**extra}]
        findings=scan_integrity(data)["findings"]
        assert any(x["code"]=="INDEX_NULL_OR_MISSING_KEY" and index_name in x["description"] for x in findings),(collection,index_name)
        assert any(x["code"]=="INDEX_COLLISION" and index_name in x["description"] for x in findings),(collection,index_name)

def test_explicit_null_and_missing_share_conservative_unique_key_bucket():
    data=base(); data["trucks"]=[{"id":"T1","tenant_id":TA,"truck_number":None},{"id":"T2","tenant_id":TA}]
    found=scan_integrity(data)["findings"]
    assert sum(x["code"]=="INDEX_NULL_OR_MISSING_KEY" and "uq_trucks_tenant_truck_number" in x["description"] for x in found)==2
    assert any(x["code"]=="INDEX_COLLISION" and "uq_trucks_tenant_truck_number" in x["description"] for x in found)
    data["trucks"]=[{"id":"T1","tenant_id":TA,"truck_number":"1"},{"id":"T2","tenant_id":TA,"truck_number":"2"}]
    assert not any(x["code"]=="INDEX_COLLISION" and "truck_number" in x["description"] for x in scan_integrity(data)["findings"])

def modern_chain(fingerprint="fp"):
    data=base(); data["loads"][0]["invoice_status"]="ready_for_submission"
    data["invoice_readiness_cases"]=[{"id":"R","tenant_id":TA,"load_id":"L1","execution_session_id":"S","status":"invoiced","version":3,"invoice_id":"I","invoice_package_id":"P","financial_basis_fingerprint":fingerprint}]
    data["execution_sessions"]=[{"id":"S","tenant_id":TA,"load_id":"L1","status":"completed","execution_state":"completed","custody_state":"completed","version":4}]
    data["invoice_packages"]=[{"id":"P","tenant_id":TA,"load_id":"L1","readiness_case_id":"R","invoice_id":"I","financial_basis_fingerprint":fingerprint}]
    data["invoices"]=[{"id":"I","tenant_id":TA,"load_id":"L1","readiness_case_id":"R","package_id":"P","financial_basis_fingerprint":fingerprint,"status":"ready_for_submission"}]
    return data

def test_exact_modern_invoice_chain_is_valid():
    bad={"INVOICED_READINESS_INVOICE_ID_MISSING","READINESS_INVOICE_MISSING","READINESS_INVOICE_RECIPROCITY_MISMATCH","READINESS_PACKAGE_MISSING","PACKAGE_READINESS_RECIPROCITY_MISMATCH","PACKAGE_INVOICE_RECIPROCITY_MISMATCH","INVOICE_PACKAGE_RECIPROCITY_MISMATCH","FINANCIAL_BASIS_FINGERPRINT_MISMATCH"}
    assert not bad&set(codes(scan_integrity(modern_chain())))

def test_same_load_legacy_or_wrong_modern_invoice_never_satisfies_readiness():
    data=modern_chain(); data["invoice_readiness_cases"][0].pop("invoice_id"); data["invoices"]=[{"id":"LEG","tenant_id":TA,"load_id":"L1","status":"ready_for_submission"}]
    result=set(codes(scan_integrity(data))); assert "INVOICED_READINESS_INVOICE_ID_MISSING" in result and "LEGACY_INVOICE_AUTHORITY" in result
    data=modern_chain(); data["invoices"][0]["readiness_case_id"]="OTHER"
    assert "READINESS_INVOICE_RECIPROCITY_MISMATCH" in codes(scan_integrity(data))

def test_invoice_missing_wrong_package_and_package_reciprocity():
    data=modern_chain(); data["invoices"]=[]
    assert "READINESS_INVOICE_MISSING" in codes(scan_integrity(data))
    data=modern_chain(); data["invoices"][0]["package_id"]="OTHER"
    assert "INVOICE_PACKAGE_RECIPROCITY_MISMATCH" in codes(scan_integrity(data))
    data=modern_chain(); data["invoice_packages"][0].update({"readiness_case_id":"OTHER","invoice_id":"OTHER"})
    result=set(codes(scan_integrity(data))); assert {"PACKAGE_READINESS_RECIPROCITY_MISMATCH","PACKAGE_INVOICE_RECIPROCITY_MISMATCH"}<=result

def test_invoice_cross_tenant_conflict_and_basis_comparison():
    data=modern_chain(); data["tenants"].append({"id":TB}); data["invoice_packages"][0]["tenant_id"]=TB
    assert "READINESS_PACKAGE_SCOPE_MISMATCH" in codes(scan_integrity(data))
    data=modern_chain(); data["invoice_packages"][0]["financial_basis_fingerprint"]="different"
    assert "FINANCIAL_BASIS_FINGERPRINT_MISMATCH" in codes(scan_integrity(data))
    data=modern_chain(); data["invoice_packages"][0].pop("financial_basis_fingerprint")
    result=set(codes(scan_integrity(data))); assert "FINANCIAL_BASIS_NOT_COMPARABLE" in result and "FINANCIAL_BASIS_FINGERPRINT_MISMATCH" not in result

def test_legacy_and_modern_invoice_authority_conflict():
    data=modern_chain(); data["invoices"].append({"id":"LEG","tenant_id":TA,"load_id":"L1","status":"Ready to Invoice"})
    assert "LEGACY_MODERN_INVOICE_AUTHORITY_CONFLICT" in codes(scan_integrity(data))

def test_partial_modern_invoice_binding_is_not_healthy_legacy():
    for binding in ({"readiness_case_id":"R"},{"package_id":"P"}):
        data=base();data["invoices"]=[{"id":"I","tenant_id":TA,"load_id":"L1",**binding}]
        result=set(codes(scan_integrity(data)))
        assert "MODERN_INVOICE_AUTHORITY_INCOMPLETE" in result
        assert "LEGACY_INVOICE_AUTHORITY" not in result

def test_delivery_modern_and_legacy_classification():
    data=base(); data["loads"][0]["stage"]="Delivered"
    result=set(codes(scan_integrity(data))); assert "LEGACY_DELIVERY_EVIDENCE_UNVERIFIABLE" in result and "MODERN_DELIVERY_EVIDENCE_MISSING" not in result
    data["execution_sessions"]=[{"id":"S","tenant_id":TA,"load_id":"L1","status":"active","execution_state":"in_transit","version":1}]
    assert "MODERN_DELIVERY_EVIDENCE_MISSING" in codes(scan_integrity(data))
    data["execution_sessions"][0].update({"status":"completed","execution_state":"completed","custody_state":"completed"})
    assert "MODERN_DELIVERY_EVIDENCE_MISSING" not in codes(scan_integrity(data))

def test_modern_readiness_missing_execution_basis_and_cross_tenant_execution():
    data=base(); data["loads"][0]["stage"]="Delivered"; data["invoice_readiness_cases"]=[{"id":"R","tenant_id":TA,"load_id":"L1","execution_session_id":"missing","status":"ready","version":1}]
    assert {"ORPHAN_REFERENCE","MODERN_DELIVERY_EVIDENCE_MISSING"}<=set(codes(scan_integrity(data)))
    data["tenants"].append({"id":TB}); data["execution_sessions"]=[{"id":"missing","tenant_id":TB,"load_id":"L1","status":"completed","version":1}]
    assert "CROSS_TENANT_REFERENCE" in codes(scan_integrity(data))

def test_truncation_less_exact_and_greater_than_limit():
    one=base(); one["documents"]=[{"id":"D1","tenant_id":TA,"load_id":"L1","doc_type":"unknown","filename":"a","url":"https://files.test/a"}]
    assert scan_integrity(one,max_findings=2)["summary"]["truncated"] is False
    exact=scan_integrity(one,max_findings=1); assert exact["summary"]["total_detected_findings"]==1 and exact["summary"]["truncated"] is False
    two=base(); two["documents"]=[{"id":"D1","tenant_id":TA,"load_id":"L1","doc_type":"unknown","filename":"a","url":"https://files.test/a"},{"id":"D2","tenant_id":TA,"load_id":"L1","doc_type":"unknown","filename":"b","url":"https://files.test/b"}]
    report=scan_integrity(two,max_findings=1); assert report["summary"]["total_detected_findings"]==2 and report["summary"]["returned_findings"]==1 and report["summary"]["truncated"] is True
