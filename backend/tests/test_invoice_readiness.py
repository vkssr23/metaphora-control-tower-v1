from decimal import Decimal
import pytest
from app.domain.invoice_readiness import base_charge,calculate,evaluate,canonical_hash,evidence_ok,select_current_rate,basis_fingerprint,invalidation_plan

LOAD={"id":"L1","stage":"Delivered","rate":9999,"rpm":99}
SESSION={"id":"S1","version":3,"status":"completed","execution_state":"delivery_confirmed","actual_snapshot":{"delivery_confirmed_at":"now"}}
RATE={"id":"R1","version":2,"revision":2,"document_id":"RC","status":"accepted","extracted_fields":{"total_rate":"1200.10","detention_rate":50}}
DOCS=[{"id":"POD","doc_type":"pod"},{"id":"RC","doc_type":"rate_con"},{"id":"LUMP","doc_type":"lumper"}]

def test_base_uses_explicit_accepted_fields_not_profitability_or_rpm():
 assert base_charge(RATE)==(Decimal("1200.10"),"total_rate")
 assert base_charge({"extracted_fields":{}})==(None,"insufficient_data")
def test_decimal_calculation_deductions_and_determinism():
 a=[{"id":"a","type":"lumper","amount":"0.20","currency":"USD","status":"approved"}];d=[{"id":"d","type":"credit","amount":"0.10","currency":"USD","status":"approved"}]
 expected={"base_charge":"0.10","accessorial_total":"0.20","deductions_total":"0.10","billable_total":"0.20","currency":"USD","line_items":[{"id":"a","type":"lumper","amount":"0.20"}],"calculation_policy":"invoice-readiness-v1"}
 assert calculate("0.10",a,d)==expected==calculate("0.10",a,d)
def test_money_rejects_invalid_negative_and_currency_mismatch():
 for value in ("NaN","Infinity",-1):
  with pytest.raises(ValueError):calculate(value)
 with pytest.raises(ValueError):calculate(10,[{"id":"a","type":"toll","amount":1,"currency":"CAD","status":"approved"}])
def test_pod_rate_and_delivery_are_fail_closed():
 for load,session,rate,docs,blocker in (({**LOAD,"stage":"In Transit"},SESSION,RATE,DOCS,"load_stage_delivered"),(LOAD,None,RATE,DOCS,"execution_session_current"),(LOAD,SESSION,None,DOCS,"rate_confirmation_current"),(LOAD,SESSION,RATE,[DOCS[1]],"pod_present")):
  assert blocker in evaluate(load,session,rate,docs)["blockers"]
def test_accessorial_evidence_and_approval_policy():
 lumper={"id":"a","type":"lumper","amount":20,"currency":"USD","status":"approved","evidence_document_ids":[]};assert not evidence_ok(lumper,DOCS)
 lumper["evidence_document_ids"]=["LUMP"];assert evidence_ok(lumper,DOCS)
 assert evaluate(LOAD,SESSION,RATE,DOCS,[lumper])["calculation"]["billable_total"]=="1220.10"
def test_stale_rate_and_blocking_exception_block():
 stale={**RATE,"superseded_by":"R2"};assert "rate_confirmation_current" in evaluate(LOAD,SESSION,stale,DOCS)["blockers"]
 assert "no_blocking_finance_exception" in evaluate(LOAD,SESSION,RATE,DOCS,exceptions=[{"blocking":True,"status":"open"}])["blockers"]
def test_package_hash_is_canonical_and_bounded():
 a={"readiness_case_id":"C","readiness_case_version":1,"load_id":"L","invoice_id":"I","calculation_snapshot":{"billable_total":"1.00"},"document_ids":["D"],"raw":"secret"};b={**a,"raw":"different"}
 assert canonical_hash(a)==canonical_hash(b) and len(canonical_hash(a))==64

def test_current_rate_selection_requires_exact_document_relationship():
 candidates=[{**RATE,"tenant_id":"T","load_id":"L1"}];docs=[{"id":"RC","tenant_id":"T","load_id":"L1","doc_type":"rate_con"}]
 assert select_current_rate("L1","T",candidates,docs)[0]["id"]=="R1"
 for bad in ([],[{**docs[0],"doc_type":"pod"}],[{**docs[0],"load_id":"L2"}],[{**docs[0],"tenant_id":"X"}]):assert select_current_rate("L1","T",candidates,bad)[0] is None
def test_current_rate_selection_never_falls_back_to_historical_acceptance():
 old={**RATE,"tenant_id":"T","load_id":"L1","revision":1};new={**old,"id":"R2","revision":2,"status":"draft"};docs=[{"id":"RC","tenant_id":"T","load_id":"L1","doc_type":"rate_con"}]
 assert select_current_rate("L1","T",[old,new],docs)==(None,"rate_confirmation_stale")
def test_same_dollar_different_basis_has_different_fingerprint():
 docs=[{"id":"P","doc_type":"pod","uploaded_at":"x"},{"id":"RC","doc_type":"rate_con","uploaded_at":"x"}];calc=calculate(5000)
 one=basis_fingerprint(LOAD,SESSION,RATE,docs,calculation=calc);two=basis_fingerprint(LOAD,SESSION,{**RATE,"id":"R2","version":3},docs,calculation=calc)
 assert one!=two
def test_invalidation_plan_reopens_approved_and_preserves_basis():
 case={"id":"C","version":4,"status":"approved","verdict":"ready","approved_at":"a","approved_by":"U","calculation_snapshot":{"billable_total":"1.00"},"financial_basis_fingerprint":"h","findings":[],"basis_history":[]}
 plan=invalidation_plan(case,"billing_document_changed",["pod"],"now","U2");u=plan["update"]
 assert u["status"]=="reopened" and u["verdict"]=="pending" and u["version"]==5 and u["basis_history"][0]["calculation_snapshot"]==case["calculation_snapshot"] and u["findings"][0]["type"]=="calculation_stale"
def test_invalidation_plan_blocks_creating_and_invoiced():
 for case in ({"id":"C","version":1,"status":"approved","invoice_creation_state":"creating"},{"id":"C","version":1,"status":"invoiced"}):
  with pytest.raises(ValueError):invalidation_plan(case,"invoice_basis_changed",[],"now","U")
