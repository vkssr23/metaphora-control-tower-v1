"""
End-to-end scenario matrix for the Metaphora Verify -> Party Verification
integration (PR #25's fix), run through the REAL route/domain code path —
not an isolated unit test. Reuses test_phase_2g_golden_flow.py's golden_api
fixture (real FastAPI app, real domain logic, FakeDB in place of Mongo, a
header-based test-auth override in place of a live JWT) — the same harness
this repo already uses for its one full-lifecycle regression test — rather
than inventing a second one.

What this proves that no other test in this repo proves: a load created
through /api/loads, with a rate confirmation extraction accepted through the
real /rate-confirmation-extractions submit->compare->accept pipeline
(broker_mc carried on that real extraction, not injected directly into a
case dict), reaches /party-verification-cases/{id}/evaluate and produces the
correct findings/blocking behavior for each of the four contract states
Metaphora Verify can return. Only party_verification_client.fetch_broker_verification
itself is mocked (the actual outbound HTTP call to the separately-deployed
Verify service) — every layer of Control Tower's own code between the API
boundary and that call is real.

Limitation, stated plainly: this does not reach across the network to the
real deployed Verify service — that would need a live elevated-role account
against staging-certification, which this session does not have (public
signup can only mint a "viewer" account, and no admin/owner credential was
available). The real Verify contract itself was independently confirmed
separately, live, against Metaphora Verify's actual production API.
"""
import pytest
from fastapi import Header, HTTPException
from fastapi.testclient import TestClient

from test_phase_2g_golden_flow import golden_api, TENANT, RC_BYTES, FIELDS  # noqa: F401 (fixture)
from app.infrastructure import party_verification_client


def ok(response, stage, expected=(200, 201)):
    assert response.status_code in expected, f"{stage}: {response.status_code} {response.text}"
    return response.json()


def h(user):
    return {"X-Test-User": user}


def _build_case_with_broker_mc(client, broker_mc: str):
    """Real load -> real uploaded rate-con doc -> real extraction ->
    submit -> compare -> accept -> real party-verification case, exactly
    the golden-flow sequence, parameterized on the one field this
    integration reads: broker_mc."""
    driver = ok(client.post("/api/drivers", json={
        "name": "Scenario Driver", "status": "Available", "cdl_expiry": "2030-01-01",
        "medical_expiry": "2030-01-01", "mvr_status": "Clear", "clearinghouse_status": "Clear",
        "employment_verification": "Complete"}, headers=h("safety")), "driver")
    truck = ok(client.post("/api/trucks", json={
        "truck_number": f"SC-{broker_mc}", "status": "Available", "maintenance_status": "Good",
        "insurance_expiry": "2030-01-01"}, headers=h("safety")), "truck")

    load_payload = {
        "customer": "Scenario Shipper", "broker": "Scenario Broker",
        "pickup_address": "1 Main St", "pickup_city": "Chicago", "pickup_state": "IL",
        "pickup_zip": "60601", "pickup_appt": "2026-09-01T10:00:00",
        "delivery_address": "2 Oak St", "delivery_city": "Boston", "delivery_state": "MA",
        "delivery_zip": "02108", "delivery_appt": "2026-09-02T10:00:00",
        "rate": 1500, "miles": 500, "commodity": "General", "weight": 1000,
        "equipment_type": "Power Only", "rate_con_number": "SC-1",
        "driver_id": driver["id"], "truck_id": truck["id"],
    }
    load = ok(client.post("/api/loads", json=load_payload, headers=h("ops")), "load")
    lid = load["id"]

    rc = ok(client.post("/api/documents/upload", data={"load_id": lid, "doc_type": "rate_con"},
                         files={"file": ("scenario-rc.pdf", RC_BYTES, "application/pdf")},
                         headers=h("ops")), "rc upload")

    fields = {**FIELDS, "total_rate": 1500, "loaded_miles": 500,
              "broker_name": "Scenario Broker", "broker_mc": broker_mc,
              "broker_contact_name": "Scenario Contact", "broker_contact_email": "contact@scenario.example",
              "customer_reference": "", "commodity": "General", "weight": 1000,
              "equipment_type": "Power Only", "pickup_name": "Scenario Shipper", "pickup_number": "SC-1",
              "pickup_address": "1 Main St", "pickup_date": "2026-09-01", "pickup_time_start": "10:00",
              "delivery_address": "2 Oak St", "delivery_date": "2026-09-02", "delivery_time_start": "10:00"}
    extraction = ok(client.post(f"/api/loads/{lid}/rate-confirmation-extractions",
                                 json={"document_id": rc["id"], "source": "manual", "extracted_fields": fields},
                                 headers=h("ops")), "rc extraction")
    rid = extraction["id"]
    ok(client.post(f"/api/rate-confirmation-extractions/{rid}/submit", json={}, headers=h("ops")), "rc submit")
    ok(client.post(f"/api/rate-confirmation-extractions/{rid}/compare", json={}, headers=h("ops")), "rc compare")
    ok(client.post(f"/api/rate-confirmation-extractions/{rid}/accept", json={}, headers=h("owner")), "rc accept")

    # A party-verification case can only be created against an approved
    # Load Passport — same prerequisite the golden-flow test exercises.
    passport = ok(client.post(f"/api/loads/{lid}/passport", json={"trailer_identifier": "TRL-SC1"},
                               headers=h("ops")), "passport")
    pid = passport["id"]
    for checkpoint in passport["checkpoints"]:
        actor = "finance" if checkpoint["type"] == "profitability" else "owner"
        ok(client.put(f"/api/load-passports/{pid}/checkpoints/{checkpoint['type']}",
                      json={"status": "pass", "source": "manual", "evidence_document_ids": [rc["id"]]},
                      headers=h(actor)), f"passport checkpoint {checkpoint['type']}")
    ok(client.post(f"/api/load-passports/{pid}/submit", json={}, headers=h("ops")), "passport submit")
    ok(client.post(f"/api/load-passports/{pid}/approve", json={}, headers=h("owner")), "passport approve")

    party = ok(client.post(f"/api/loads/{lid}/party-verification-case", json={}, headers=h("ops")), "party create")
    pvc_id = party["id"]
    # /evaluate only flips status to "findings_open" once the case is past
    # "draft" (party_verification_routes.py's evaluate_case: target status
    # stays unchanged unless status was already "review_pending") — submit
    # first, matching how this case would actually reach evaluation in use.
    ok(client.post(f"/api/party-verification-cases/{pvc_id}/submit", json={}, headers=h("ops")), "party submit")
    return pvc_id


def _evaluate(client, pvc_id):
    return ok(client.post(f"/api/party-verification-cases/{pvc_id}/evaluate", json={}, headers=h("ops")), "evaluate")


# ---------------------------------------------------------------------
# Scenario 1: active broker, valid required bond -> no broker-authority
# or bond blocker.
# ---------------------------------------------------------------------
def test_scenario_active_broker_valid_bond_no_blocker(golden_api, monkeypatch):
    client, db, storage = golden_api

    async def fake_verify(settings, rate):
        return {"status": "ok", "broker_authority_status": "ACTIVE",
                "bond_insurance_required": "REQUIRED", "bond_insurance_on_file": "PRESENT",
                "risk_level": "Green", "flags": []}
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", fake_verify)

    pvc_id = _build_case_with_broker_mc(client, "MC-ACTIVE-1")
    result = _evaluate(client, pvc_id)
    types = {f["type"] for f in result["findings"]}
    assert "verify_broker_authority_inactive" not in types
    assert "verify_broker_bond_not_on_file" not in types
    assert not any(f["blocking"] for f in result["findings"] if f["type"].startswith("verify_broker"))


# ---------------------------------------------------------------------
# Scenario 2: unknown broker authority -> verification warning only,
# never a block.
# ---------------------------------------------------------------------
def test_scenario_unknown_broker_authority_is_warning_not_block(golden_api, monkeypatch):
    client, db, storage = golden_api

    async def fake_verify(settings, rate):
        return {"status": "ok", "broker_authority_status": "UNKNOWN",
                "bond_insurance_required": "REQUIRED", "bond_insurance_on_file": "UNKNOWN",
                "risk_level": "Yellow", "flags": []}
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", fake_verify)

    pvc_id = _build_case_with_broker_mc(client, "MC-UNKNOWN-1")
    result = _evaluate(client, pvc_id)
    auth_finding = next(f for f in result["findings"] if f["type"] == "verify_broker_authority_not_on_file")
    bond_finding = next(f for f in result["findings"] if f["type"] == "verify_broker_bond_unverified")
    assert auth_finding["blocking"] is False and auth_finding["severity"] == "warning"
    assert bond_finding["blocking"] is False and bond_finding["severity"] == "warning"
    # Scoped to this integration's own findings: the fixture load has no
    # insurance evidence uploaded, which independently (and correctly)
    # produces its own blocking "insurance_document_missing" finding from
    # party_verification.py's internal rules — a real, unrelated finding,
    # not something this scenario is testing.
    assert not any(f["blocking"] for f in result["findings"] if f["type"].startswith("verify_broker"))


# ---------------------------------------------------------------------
# Scenario 3: explicit inactive/out-of-service/unauthorized broker
# authority -> blocking finding.
# ---------------------------------------------------------------------
@pytest.mark.parametrize("negative_status", ["INACTIVE", "OUT_OF_SERVICE", "NOT_AUTHORIZED"])
def test_scenario_explicit_negative_authority_blocks(golden_api, monkeypatch, negative_status):
    client, db, storage = golden_api

    async def fake_verify(settings, rate):
        return {"status": "ok", "broker_authority_status": negative_status,
                "bond_insurance_required": "NOT_REQUIRED", "bond_insurance_on_file": "ABSENT",
                "risk_level": "Red", "flags": []}
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", fake_verify)

    pvc_id = _build_case_with_broker_mc(client, f"MC-{negative_status}")
    result = _evaluate(client, pvc_id)
    finding = next(f for f in result["findings"] if f["type"] == "verify_broker_authority_inactive")
    assert finding["blocking"] is True
    assert result["status"] == "findings_open"
    assert "verify_broker_authority_inactive" in result["blocking_reasons"]


# ---------------------------------------------------------------------
# Scenario 4: required bond affirmatively absent -> blocking finding,
# even with active authority.
# ---------------------------------------------------------------------
def test_scenario_required_bond_absent_blocks(golden_api, monkeypatch):
    client, db, storage = golden_api

    async def fake_verify(settings, rate):
        return {"status": "ok", "broker_authority_status": "ACTIVE",
                "bond_insurance_required": "REQUIRED", "bond_insurance_on_file": "ABSENT",
                "risk_level": "Red", "flags": []}
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", fake_verify)

    pvc_id = _build_case_with_broker_mc(client, "MC-NOBOND-1")
    result = _evaluate(client, pvc_id)
    finding = next(f for f in result["findings"] if f["type"] == "verify_broker_bond_not_on_file")
    assert finding["blocking"] is True
    assert "verify_broker_authority_inactive" not in {f["type"] for f in result["findings"]}
    assert result["status"] == "findings_open"


# ---------------------------------------------------------------------
# Missing/stale provider response -> unavailable evidence, not a negative.
# ---------------------------------------------------------------------
def test_scenario_verify_unavailable_is_informational_not_negative(golden_api, monkeypatch):
    client, db, storage = golden_api

    async def fake_verify(settings, rate):
        return {"status": "unavailable"}
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", fake_verify)

    pvc_id = _build_case_with_broker_mc(client, "MC-DOWN-1")
    result = _evaluate(client, pvc_id)
    finding = next(f for f in result["findings"] if f["type"] == "verify_broker_check_unavailable")
    assert finding["blocking"] is False and finding["severity"] == "info"
