"""METAPHORA GOLDEN FREIGHT FLOW V1 — one coherent application lifecycle."""
import copy
import hashlib
import os

os.environ.update({"JWT_SECRET": "isolated-test-only-secret-value-over-32-characters", "MONGO_URL": "mongodb://127.0.0.1:1/no-network-test", "DB_NAME": "isolated", "CORS_ORIGINS": "http://localhost:3000", "APP_ENV": "test", "ALLOW_SEED_ENDPOINT": "false"})

import pytest
from fastapi import Header, HTTPException
from fastapi.testclient import TestClient

import server
from app.api import document_routes
from app.application.action_center_service import SOURCE_COLLECTIONS
from app.infrastructure.local_document_storage import LocalDocumentStorage
from test_rate_confirmation_routes import Collection, FakeDB, FIELDS, USERS, h

TENANT = "ten_" + "a" * 32
FOREIGN = "ten_" + "b" * 32
RC_BYTES = b"%PDF-1.7\nMETAPHORA GOLDEN RC 1500 USD\n%%EOF"
POD_BYTES = b"%PDF-1.7\nMETAPHORA GOLDEN POD DELIVERED\n%%EOF"

USERS.setdefault("safety", {"id": "U-safe", "email": "safe@example.test", "name": "Safety", "role": "safety", "tenant_id": TENANT})


@pytest.fixture
def golden_api(monkeypatch, tmp_path):
    db = FakeDB()
    names = {
        "tenants", "party_verification_cases", "execution_eligibility_cases",
        "pickup_release_cases", "execution_sessions", "execution_events",
        "execution_exceptions", "invoice_readiness_cases", "invoice_packages",
        "invoices", "operations", "outbox_events", "reconciliation_items",
        "action_items", "production_integrity_findings", "drivers", "trucks",
    } | set(SOURCE_COLLECTIONS)
    for name in names:
        if not hasattr(db, name):
            setattr(db, name, Collection(name, db.events))
    db.tenants.docs = [{"id": TENANT, "name": "Golden Carrier", "usdot": "123456", "mc": "MC123"}, {"id": FOREIGN, "name": "Foreign"}]
    db.users.docs = [copy.deepcopy(v) for v in USERS.values()]
    storage = LocalDocumentStorage(tmp_path)
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(document_routes, "get_document_storage", lambda: storage)
    server.app.dependency_overrides.clear()

    async def actor(x_test_user: str = Header("ops")):
        user = USERS.get(x_test_user, USERS["ops"])
        record = await db.users.find_one({"id": user["id"]})
        if not record:
            raise HTTPException(401, "User unavailable")
        record.pop("_id", None)
        return record

    server.app.dependency_overrides[server.get_current_user] = actor
    yield TestClient(server.app), db, storage
    server.app.dependency_overrides.clear()


def ok(response, stage, expected=(200, 201)):
    assert response.status_code in expected, f"{stage}: {response.status_code} {response.text}"
    return response.json()


def upload_pdf(client, load_id, doc_type, name, content):
    return ok(client.post("/api/documents/upload", data={"load_id": load_id, "doc_type": doc_type},
                          files={"file": (name, content, "application/pdf")}, headers=h("ops")), f"{doc_type} upload")


def test_metaphora_golden_freight_flow_v1(golden_api):
    client, db, storage = golden_api

    # Tenant-scoped fleet and load creation use normal authenticated routes.
    driver = ok(client.post("/api/drivers", json={"name": "Golden Driver", "status": "Available", "cdl_expiry": "2030-01-01", "medical_expiry": "2030-01-01", "mvr_status": "Clear", "clearinghouse_status": "Clear", "employment_verification": "Complete"}, headers=h("safety")), "driver")
    truck = ok(client.post("/api/trucks", json={"truck_number": "G-101", "status": "Available", "maintenance_status": "Good", "insurance_expiry": "2030-01-01"}, headers=h("safety")), "truck")
    load_payload = {"customer": "Golden Shipper", "broker": "Golden Broker", "pickup_address": "1 Main St", "pickup_city": "Chicago", "pickup_state": "IL", "pickup_zip": "60601", "pickup_appt": "2026-09-01T10:00:00", "delivery_address": "2 Oak St", "delivery_city": "Boston", "delivery_state": "MA", "delivery_zip": "02108", "delivery_appt": "2026-09-02T10:00:00", "rate": 1500, "miles": 500, "commodity": "General", "weight": 1000, "equipment_type": "Power Only", "driver_id": driver["id"], "truck_id": truck["id"], "rate_con_number": "GRC-1"}
    load = ok(client.post("/api/loads", json=load_payload, headers=h("ops")), "load")
    lid = load["id"]
    assert load["stage"] == "Booked" and load["tenant_id"] == TENANT

    # Real immutable RC bytes precede structured evidence and explicit acceptance.
    rc = upload_pdf(client, lid, "rate_con", "golden-rc.pdf", RC_BYTES)
    rc_record = next(x for x in db.documents.docs if x["id"] == rc["id"])
    rc_key, rc_hash = rc_record["storage_key"], hashlib.sha256(RC_BYTES).hexdigest()
    assert rc["sha256"] == rc_hash and storage.open(rc_key).read() == RC_BYTES
    assert not db.rate_confirmation_extractions.docs
    fields = {**FIELDS, "total_rate": 1500, "loaded_miles": 500, "broker_name": "Golden Broker", "broker_contact_name": "Golden Contact", "broker_contact_email": "contact@golden.example", "customer_reference": "", "commodity": "General", "weight": 1000, "equipment_type": "Power Only", "pickup_name": "Golden Shipper", "pickup_number": "GRC-1", "pickup_address": "1 Main St", "pickup_date": "2026-09-01", "pickup_time_start": "10:00", "delivery_address": "2 Oak St", "delivery_date": "2026-09-02", "delivery_time_start": "10:00"}
    extraction = ok(client.post(f"/api/loads/{lid}/rate-confirmation-extractions", json={"document_id": rc["id"], "source": "manual", "extracted_fields": fields}, headers=h("ops")), "RC extraction")
    rid = extraction["id"]
    ok(client.post(f"/api/rate-confirmation-extractions/{rid}/submit", json={}, headers=h("ops")), "RC submit")
    compared = ok(client.post(f"/api/rate-confirmation-extractions/{rid}/compare", json={}, headers=h("ops")), "RC compare")
    assert not [d for d in compared["discrepancies"] if d.get("blocking")]
    accepted = ok(client.post(f"/api/rate-confirmation-extractions/{rid}/accept", json={}, headers=h("owner")), "RC accept")
    assert accepted["status"] == "accepted" and accepted["document_id"] == rc["id"]

    # Passport, party review, and eligibility are reached through their authorities.
    passport = ok(client.post(f"/api/loads/{lid}/passport", json={"trailer_identifier": "TRL-G1"}, headers=h("ops")), "passport")
    pid = passport["id"]
    insurance = upload_pdf(client, lid, "insurance", "golden-insurance.pdf", RC_BYTES)
    # Phase 1A permits controlled manual checkpoint review; later Phase 1C/1D
    # transitions replace their owned checkpoints with source-derived evidence.
    for checkpoint in passport["checkpoints"]:
        actor = "finance" if checkpoint["type"] == "profitability" else "owner"
        ok(client.put(f"/api/load-passports/{pid}/checkpoints/{checkpoint['type']}", json={"status": "pass", "source": "manual", "evidence_document_ids": [rc["id"]]}, headers=h(actor)), f"passport checkpoint {checkpoint['type']}")
    ok(client.post(f"/api/load-passports/{pid}/submit", json={}, headers=h("ops")), "passport submit")
    ok(client.post(f"/api/load-passports/{pid}/approve", json={}, headers=h("owner")), "passport approve")
    party = ok(client.post(f"/api/loads/{lid}/party-verification-case", json={}, headers=h("ops")), "party create")
    pvc = party["id"]
    ok(client.post(f"/api/party-verification-cases/{pvc}/submit", json={}, headers=h("ops")), "party submit")
    for domain in party["required_review_domains"]:
        actor = "safety" if domain in {"carrier_authority", "fraud_risk"} else "finance" if domain in {"contact_validation", "insurance_evidence"} else "ops"
        ok(client.put(f"/api/party-verification-cases/{pvc}/reviews/{domain}", json={"result": "match", "source": "manual", "evidence_document_ids": [insurance["id"]]}, headers=h(actor)), f"party review {domain}")
    cleared = ok(client.post(f"/api/party-verification-cases/{pvc}/clear", json={}, headers=h("owner")), "party clear")
    assert cleared["status"] == "cleared"

    eligibility = ok(client.post(f"/api/loads/{lid}/execution-eligibility-case", json={"trailer_identifier": "TRL-G1", "trailer_equipment_type": "Power Only"}, headers=h("ops")), "eligibility create")
    eid = eligibility["id"]
    ok(client.post(f"/api/execution-eligibility-cases/{eid}/submit", json={}, headers=h("ops")), "eligibility submit")
    ok(client.post(f"/api/execution-eligibility-cases/{eid}/refresh", json={}, headers=h("safety")), "eligibility refresh")
    ok(client.put(f"/api/execution-eligibility-cases/{eid}/hos-readiness", json={"available_drive_hours": 20, "required_trip_hours": 10}, headers=h("ops")), "HOS")
    evaluated = ok(client.post(f"/api/execution-eligibility-cases/{eid}/evaluate", json={}, headers=h("safety")), "eligibility evaluate")
    for check in evaluated["checks"]:
        if check["result"] != "pass":
            actor = "safety" if check["type"] in {"cdl_administrative_status", "medical_card_administrative_status", "mvr_administrative_status", "clearinghouse_administrative_status", "employment_verification_status", "truck_maintenance_condition", "truck_insurance_evidence", "truck_equipment_compatibility", "trailer_equipment_compatibility", "load_weight_fit", "commodity_equipment_fit", "driver_operational_status", "truck_operational_status"} else "ops"
            ok(client.put(f"/api/execution-eligibility-cases/{eid}/checks/{check['type']}", json={"result": "pass", "source": "manual"}, headers=h(actor)), f"eligibility check {check['type']}")
    evaluated = ok(client.post(f"/api/execution-eligibility-cases/{eid}/evaluate", json={}, headers=h("safety")), "eligibility reevaluate")
    for check_type in evaluated["warning_reasons"]:
        ok(client.put(f"/api/execution-eligibility-cases/{eid}/checks/{check_type}", json={"result": "waived", "source": "manual", "reason": "Bounded synthetic pilot fixture"}, headers=h("owner")), f"eligibility waiver {check_type}")
    # Final eligibility binds the Passport version produced by party clearance.
    eligible = ok(client.post(f"/api/execution-eligibility-cases/{eid}/eligible", json={}, headers=h("owner")), "eligibility final")
    assert eligible["status"] == "eligible"

    # Phase 1E consumes the current Passport/RC/party/eligibility basis.
    pickup = ok(client.post(f"/api/loads/{lid}/pickup-release-case", json={}, headers=h("ops")), "pickup create")
    prid = pickup["id"]
    ok(client.post(f"/api/pickup-release-cases/{prid}/submit", json={}, headers=h("ops")), "pickup submit")
    release_eval = ok(client.post(f"/api/pickup-release-cases/{prid}/evaluate", json={}, headers=h("ops")), "pickup evaluate")
    assert release_eval["verdict"] == "release_ready", f"pickup blockers={release_eval.get('blocking_reasons')} checklist={release_eval.get('checklist_items')}"
    ok(client.post(f"/api/pickup-release-cases/{prid}/release-ready", json={}, headers=h("owner")), "pickup ready")
    released = ok(client.post(f"/api/pickup-release-cases/{prid}/release", json={}, headers=h("owner")), "pickup release")
    confirmed = ok(client.post(f"/api/pickup-release-cases/{prid}/confirm-pickup", json={"source": "manual"}, headers=h("ops")), "pickup confirm")
    assert confirmed["custody_state"] == "pickup_confirmed"
    assert client.post(f"/api/pickup-release-cases/{prid}/confirm-pickup", json={"source": "manual"}, headers=h("ops")).status_code == 409

    # Current policy requires the load Loaded stage before execution starts.
    for stage in ("Assigned", "Dispatched", "Pickup Started", "Arrived Pickup", "Loaded"):
        ok(client.post(f"/api/loads/{lid}/stage", json={"stage": stage}, headers=h("ops")), f"load stage {stage}")
    execution = ok(client.post(f"/api/loads/{lid}/execution-session/start", json={}, headers=h("ops")), "execution start")
    sid = execution["id"]
    departed = ok(client.post(f"/api/execution-sessions/{sid}/stops/0/depart", json={"version": execution["version"]}, headers=h("ops")), "pickup stop depart")
    exception = ok(client.post(f"/api/execution-sessions/{sid}/exceptions", json={"version": departed["version"], "type": "driver_reported_issue", "category": "driver", "severity": "warning", "title": "Golden delay"}, headers=h("ops")), "execution exception")
    xid = exception["id"]

    action = ok(client.get("/api/action-center", headers=h("ops")), "action projection")["items"][0]
    assert action["status"] == "open" and action["source_id"] == xid
    denied = client.post(f"/api/action-center/{action['id']}/acknowledge", json={"version": action["version"]}, headers=h("finance"))
    assert denied.status_code == 403 and next(x for x in db.execution_exceptions.docs if x["id"] == xid)["status"] == "open"
    acknowledged = ok(client.post(f"/api/action-center/{action['id']}/acknowledge", json={"version": action["version"]}, headers=h("ops")), "action acknowledge")
    assert acknowledged["status"] == "acknowledged" and next(x for x in db.execution_exceptions.docs if x["id"] == xid)["status"] == "open"
    resolved_source = ok(client.put(f"/api/execution-exceptions/{xid}/resolve", json={"version": exception["version"], "reason": "Driver confirmed clear"}, headers=h("ops")), "source resolve")
    assert resolved_source["status"] == "resolved"
    refreshed = ok(client.get("/api/action-center", headers=h("ops")), "action resolution")
    resolved_action = next(x for x in db.action_items.docs if x["id"] == action["id"])
    assert resolved_action["status"] == "resolved" and resolved_action["acknowledged_by"] == "U-ops"
    ok(client.get("/api/action-center", headers=h("ops")), "action stable refresh")
    assert not [x for x in db.action_items.docs if x["source_id"] == xid and x["status"] in {"open", "acknowledged"}]

    # Delivery ordering, real POD, completion, and modern invoice authority.
    current_session = next(x for x in db.execution_sessions.docs if x["id"] == sid)
    for stage in ("In Transit", "Arrived Delivery"):
        ok(client.post(f"/api/loads/{lid}/stage", json={"stage": stage}, headers=h("ops")), f"load stage {stage}")
    arrived = ok(client.post(f"/api/execution-sessions/{sid}/delivery-arrive", json={"version": current_session["version"]}, headers=h("ops")), "delivery arrive")
    delivered = ok(client.post(f"/api/execution-sessions/{sid}/delivery-confirm", json={"version": arrived["version"], "source": "manual"}, headers=h("ops")), "delivery confirm")
    pod = upload_pdf(client, lid, "pod", "golden-pod.pdf", POD_BYTES)
    pod_record = next(x for x in db.documents.docs if x["id"] == pod["id"])
    pod_key, pod_hash = pod_record["storage_key"], hashlib.sha256(POD_BYTES).hexdigest()
    assert pod["sha256"] == pod_hash and storage.open(pod_key).read() == POD_BYTES
    completed = ok(client.post(f"/api/execution-sessions/{sid}/complete", json={"version": delivered["version"]}, headers=h("ops")), "execution complete")
    assert completed["status"] == "completed"

    readiness = ok(client.post(f"/api/loads/{lid}/invoice-readiness-case", json={}, headers=h("finance")), "readiness create")
    irid = readiness["id"]
    evaluated = ok(client.post(f"/api/invoice-readiness-cases/{irid}/evaluate", json={"version": readiness["version"]}, headers=h("finance")), "readiness evaluate")
    assert evaluated["status"] == "ready" and evaluated["billable_total"] == "1500.00"
    approved = ok(client.post(f"/api/invoice-readiness-cases/{irid}/approve", json={"version": evaluated["version"]}, headers=h("owner")), "finance approval")
    headers = {**h("owner"), "Idempotency-Key": "golden-invoice-v1"}
    invoice = ok(client.post(f"/api/invoice-readiness-cases/{irid}/invoice", json={"version": approved["version"]}, headers=headers), "invoice")
    replay = ok(client.post(f"/api/invoice-readiness-cases/{irid}/invoice", json={"version": approved["version"]}, headers=headers), "invoice replay")
    assert invoice["id"] == replay["id"] and invoice["amount"] == "1500.00"
    assert invoice["status"] == "ready_for_submission" and invoice["external_submission_status"] == "not_submitted"
    assert len(db.invoices.docs) == len(db.invoice_packages.docs) == len(db.operations.docs) == len(db.outbox_events.docs) == 1

    # The exact E2E artifacts remain isolated and immutable.
    assert client.get(f"/api/documents/{pod['id']}/download", headers=h("foreign")).status_code == 404
    assert rc_record["sha256"] == rc_hash and pod_record["sha256"] == pod_hash
    assert storage.open(rc_key).read() == RC_BYTES and storage.open(pod_key).read() == POD_BYTES
    assert all(x["tenant_id"] == TENANT for x in (driver, truck, load, rc, pod, accepted, cleared, eligible, released, completed, invoice))
    actions = {x.get("action") for x in db.audit_events.docs}
    assert {"document.upload_started", "document.created", "rate_confirmation.accepted", "action_center.acknowledged", "invoice.created"} <= actions
