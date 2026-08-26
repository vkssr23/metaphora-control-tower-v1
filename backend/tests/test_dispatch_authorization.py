"""PR1: pure canonical evaluator, idempotent append-only store, and the two
shadow-evaluation integration points (passport authorization, boundary
stage transition). Covers tri-state precedence, Verify failure/staleness,
tenant isolation, idempotency, stale load versions, existing loads, both
bypass paths, and zero behavior change while DISPATCH_GATE_ENFORCED
defaults false.
"""
import copy
import os
from dataclasses import replace

os.environ.update({"JWT_SECRET": "isolated-test-only-secret-value-over-32-characters", "MONGO_URL": "mongodb://127.0.0.1:1/no-network-test", "DB_NAME": "isolated", "CORS_ORIGINS": "http://localhost:3000", "APP_ENV": "test", "ALLOW_SEED_ENDPOINT": "false"})

import pytest

import app.infrastructure.party_verification_client as party_verification_client
import server
from app.domain import dispatch_authorization as da
from app.domain.load_passports import bounded_load_snapshot
from app.infrastructure import dispatch_authorization_store as store
from test_rate_confirmation_routes import DOC, FakeDB, LOAD, TA, TB, USERS, h

# ---------------------------------------------------------------------------
# Section A: pure canonical evaluator - tri-state precedence
# ---------------------------------------------------------------------------

def test_negative_wins_over_review_precedence():
    outcome = da.evaluate({"verify_broker_mc_not_found"}, {"verify_unavailable", "evidence_missing"})
    assert outcome.decision == da.DispatchDecision.BLOCKED
    assert outcome.reason_codes == ("verify_broker_mc_not_found",)


def test_review_required_when_only_unknowns():
    outcome = da.evaluate(set(), {"verify_not_attempted"})
    assert outcome.decision == da.DispatchDecision.REVIEW_REQUIRED
    assert outcome.reason_codes == ("verify_not_attempted",)


def test_authorized_when_clean():
    outcome = da.evaluate(set(), set())
    assert outcome.decision == da.DispatchDecision.AUTHORIZED
    assert outcome.reason_codes == ()


def test_evaluate_is_deterministic_regardless_of_input_ordering():
    a = da.evaluate({"verify_fraud_risk_red", "stage_transition_not_allowed"}, {"evidence_missing"})
    b = da.evaluate({"stage_transition_not_allowed", "verify_fraud_risk_red"}, {"evidence_missing"})
    assert a == b
    assert a.reason_codes == ("stage_transition_not_allowed", "verify_fraud_risk_red")


@pytest.mark.parametrize("verify_result,expected_negatives,expected_reviews", [
    (None, set(), {"verify_not_attempted"}),
    ({"status": "unavailable"}, set(), {"verify_unavailable"}),
    ({"status": "not_found"}, {"verify_broker_mc_not_found"}, set()),
    ({"status": "weird"}, set(), {"evidence_malformed"}),
    ({"status": "ok", "broker_authority_status": "UNKNOWN"}, set(), {"verify_broker_authority_unknown"}),
    ({"status": "ok", "broker_authority_status": "ACTIVE"}, set(), set()),
    ({"status": "ok", "broker_authority_status": "INACTIVE"}, {"verify_broker_authority_inactive"}, set()),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "risk_level": "Red"}, {"verify_fraud_risk_red"}, set()),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "risk_level": "Yellow"}, set(), {"verify_fraud_risk_yellow"}),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "REQUIRED", "bond_insurance_on_file": "ABSENT"}, {"verify_bond_insurance_absent"}, set()),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "REQUIRED", "bond_insurance_on_file": None}, set(), {"verify_bond_insurance_unknown"}),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "NOT_REQUIRED", "bond_insurance_on_file": "ABSENT"}, set(), set()),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "flags": [{"code": "SHARED_CONTACT_REVOKED_ENTITY", "message": "x"}]}, {"verify_shared_contact_revoked_entity"}, set()),
])
def test_verify_reason_codes_tri_state_vocabulary(verify_result, expected_negatives, expected_reviews):
    negatives, reviews = da.verify_reason_codes(verify_result)
    assert negatives == expected_negatives
    assert reviews == expected_reviews


def test_passport_authorization_reason_codes_missing_passport_is_review():
    negatives, reviews = da.passport_authorization_reason_codes(None, None)
    assert negatives == set() and reviews == {"evidence_missing"}


def test_passport_authorization_reason_codes_unapproved_is_negative():
    negatives, reviews = da.passport_authorization_reason_codes({"status": "draft"}, None)
    assert negatives == {"passport_not_approved"}


def test_passport_authorization_reason_codes_approved_but_not_ready_is_negative():
    negatives, reviews = da.passport_authorization_reason_codes(
        {"status": "approved", "approved_version": 2, "version": 2}, {"ready_for_pickup_authorization": False})
    assert negatives == {"passport_readiness_blocked"}


def test_passport_authorization_reason_codes_version_mismatch_is_review():
    negatives, reviews = da.passport_authorization_reason_codes(
        {"status": "approved", "approved_version": 2, "version": 3}, {"ready_for_pickup_authorization": True})
    assert negatives == set() and reviews == {"passport_version_mismatch"}


def test_boundary_stage_transition_reason_codes_disallowed_is_negative():
    negatives, reviews = da.boundary_stage_transition_reason_codes("Booked", "Closed", False)
    assert negatives == {"stage_transition_not_allowed"}


def test_boundary_stage_transition_reason_codes_missing_inputs_is_review():
    negatives, reviews = da.boundary_stage_transition_reason_codes(None, "Assigned", None)
    assert negatives == set() and reviews == {"evidence_missing"}


def test_evaluate_boundary_stage_transition_negative_from_verify_still_blocks_a_valid_transition():
    outcome = da.evaluate_boundary_stage_transition(
        verify_result={"status": "not_found"}, current_stage="Booked", requested_stage="Assigned", transition_is_allowed=True)
    assert outcome.decision == da.DispatchDecision.BLOCKED
    assert outcome.reason_codes == ("verify_broker_mc_not_found",)


# ---------------------------------------------------------------------------
# Section B: append-only, idempotent store
# ---------------------------------------------------------------------------

class _UniqueCollection:
    """Minimal fake enforcing the (tenant_id, load_id, subject, input_hash)
    unique index from index_manifest, standalone-Mongo style (no txns)."""
    def __init__(self):
        self.docs = []
        self.insert_calls = 0

    def _key(self, doc):
        return (doc["tenant_id"], doc["load_id"], doc["subject"], doc["input_hash"])

    async def insert_one(self, doc):
        self.insert_calls += 1
        if any(self._key(d) == self._key(doc) for d in self.docs):
            raise RuntimeError("E11000 duplicate key error collection: dispatch_authorization_evaluations")
        self.docs.append(dict(doc))

    async def find_one(self, query, *args):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None


def _outcome(decision="AUTHORIZED", codes=()):
    return da.DispatchOutcome(da.DispatchDecision(decision), tuple(codes))


@pytest.mark.anyio
async def test_record_evaluation_is_idempotent_on_identical_input():
    collection = _UniqueCollection()
    kwargs = dict(tenant_id=TA, load_id="L1", subject="passport_authorization", outcome=_outcome(),
                  load_version="2026-01-01T00:00:00Z", sources=[], evidence_freshness="current", gate_enforced=False)
    first = await store.record_evaluation(collection, **kwargs)
    second = await store.record_evaluation(collection, **kwargs)
    assert first["id"] == second["id"]
    assert len(collection.docs) == 1
    assert collection.insert_calls == 2  # the second attempt raced the unique index and was replayed, not skipped


@pytest.mark.anyio
async def test_record_evaluation_distinguishes_stale_load_versions():
    collection = _UniqueCollection()
    base = dict(tenant_id=TA, load_id="L1", subject="passport_authorization", outcome=_outcome(),
                sources=[], evidence_freshness="current", gate_enforced=False)
    first = await store.record_evaluation(collection, load_version="v1", **base)
    second = await store.record_evaluation(collection, load_version="v2", **base)
    assert first["id"] != second["id"]
    assert len(collection.docs) == 2
    assert first["load_version"] == "v1" and second["load_version"] == "v2"


@pytest.mark.anyio
async def test_record_evaluation_never_leaks_across_tenants():
    collection = _UniqueCollection()
    base = dict(load_id="L1", subject="passport_authorization", outcome=_outcome(),
                load_version="v1", sources=[], evidence_freshness="current", gate_enforced=False)
    a = await store.record_evaluation(collection, tenant_id=TA, **base)
    b = await store.record_evaluation(collection, tenant_id=TB, **base)
    assert a["id"] != b["id"]
    assert {d["tenant_id"] for d in collection.docs} == {TA, TB}


@pytest.mark.anyio
async def test_record_evaluation_never_stores_evidence_contents():
    collection = _UniqueCollection()
    doc = await store.record_evaluation(
        collection, tenant_id=TA, load_id="L1", subject="passport_authorization",
        outcome=_outcome("BLOCKED", ["verify_broker_authority_inactive"]), load_version="v1",
        sources=[{"source": "load", "id": "L1", "version": "v1"}], evidence_freshness="current", gate_enforced=False)
    allowed = {"id", "tenant_id", "load_id", "subject", "decision", "evaluator_version", "load_version",
               "reason_codes", "sources", "evidence_freshness", "gate_enforced", "evaluated_at", "input_hash"}
    assert set(doc) == allowed


# ---------------------------------------------------------------------------
# Section C: shadow-evaluation integration (passport authorization + boundary
# stage transition), exercised through the real HTTP endpoints.
# ---------------------------------------------------------------------------

def _load(load_id="L1", tenant=TA, stage="Assigned"):
    return {**copy.deepcopy(LOAD), "id": load_id, "tenant_id": tenant, "stage": stage, "driver_id": "D1", "truck_id": "T1"}


def _ready_passport(load, status="approved", version=1):
    return {
        "id": "lps_1", "tenant_id": load["tenant_id"], "load_id": load["id"], "version": version, "status": status,
        "approved_at": "now", "approved_by": "U-owner", "approved_version": version,
        "pickup_authorization": None, "blocking_reasons": [],
        "checkpoints": [{"type": k, "status": "pass", "blocking": True} for k in
                        ("load_details", "rate_confirmation", "broker_identity", "shipper_identity", "profitability", "appointment_feasibility", "pickup_instructions")],
        "load_snapshot": bounded_load_snapshot(load), "assignment_snapshot": {"driver_id": "D1", "truck_id": "T1"},
        "profitability_snapshot": {"estimated_net_profit": 1}, "required_checkpoint_types": [],
    }


CLEAN_VERIFY = {"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "NOT_REQUIRED",
                "bond_insurance_on_file": "ABSENT", "risk_level": "Green", "flags": []}


async def _clean_verify(settings, rate):
    return CLEAN_VERIFY


async def _unavailable_verify(settings, rate):
    return {"status": "unavailable"}


async def _not_found_verify(settings, rate):
    return {"status": "not_found"}


@pytest.fixture
def api(monkeypatch):
    from fastapi import Header, HTTPException
    from fastapi.testclient import TestClient

    db = FakeDB()
    setattr(db, "dispatch_authorization_evaluations", type(db.audit_events)("dispatch_authorization_evaluations", db.events))
    db.loads.docs = [_load("L1", TA), _load("LB", TB)]
    db.documents.docs = [copy.deepcopy(DOC)]
    monkeypatch.setattr(server, "db", db)
    server.app.dependency_overrides.clear()

    async def actor_dep(x_test_user: str = Header("ops")):
        record = await db.users.find_one({"id": USERS.get(x_test_user, USERS["ops"])["id"]})
        if not record:
            raise HTTPException(401, "User unavailable")
        record.pop("_id", None)
        return record
    server.app.dependency_overrides[server.get_current_user] = actor_dep
    yield TestClient(server.app), db
    server.app.dependency_overrides.clear()


def _shadow_records(db, load_id, subject):
    return [d for d in db.dispatch_authorization_evaluations.docs if d["load_id"] == load_id and d["subject"] == subject]


def test_passport_authorization_review_required_when_verify_not_configured_existing_load(api):
    client, db = api
    db.load_passports.docs = [_ready_passport(db.loads.docs[0])]
    response = client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    assert response.status_code == 200  # unchanged real behavior
    records = _shadow_records(db, "L1", "passport_authorization")
    assert len(records) == 1
    assert records[0]["decision"] == "REVIEW_REQUIRED"
    assert records[0]["reason_codes"] == ["verify_not_attempted"]
    assert records[0]["evidence_freshness"] == "missing"
    assert records[0]["tenant_id"] == TA


def test_passport_authorization_authorized_when_clean(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    db.load_passports.docs = [_ready_passport(db.loads.docs[0])]
    response = client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    assert response.status_code == 200
    records = _shadow_records(db, "L1", "passport_authorization")
    assert records[0]["decision"] == "AUTHORIZED"
    assert records[0]["reason_codes"] == []
    assert records[0]["evidence_freshness"] == "current"


def test_passport_authorization_bypass_path_real_endpoint_still_blocks_unapproved(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    passport = _ready_passport(db.loads.docs[0])
    passport["status"] = "draft"
    db.load_passports.docs = [passport]
    response = client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    assert response.status_code == 409  # real gate is untouched by the shadow evaluator
    records = _shadow_records(db, "L1", "passport_authorization")
    assert records[0]["decision"] == "BLOCKED"
    assert records[0]["reason_codes"] == ["passport_not_approved"]


def test_passport_authorization_verify_failure_is_review_required_not_blocked(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _unavailable_verify)
    db.load_passports.docs = [_ready_passport(db.loads.docs[0])]
    client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    records = _shadow_records(db, "L1", "passport_authorization")
    assert records[0]["decision"] == "REVIEW_REQUIRED"
    assert records[0]["reason_codes"] == ["verify_unavailable"]
    assert records[0]["evidence_freshness"] == "unavailable"


def test_passport_authorization_verify_explicit_negative_blocks_even_when_passport_is_clean(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _not_found_verify)
    db.load_passports.docs = [_ready_passport(db.loads.docs[0])]
    response = client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    assert response.status_code == 200  # real endpoint has no Verify gate today - unaffected
    records = _shadow_records(db, "L1", "passport_authorization")
    assert records[0]["decision"] == "BLOCKED"
    assert records[0]["reason_codes"] == ["verify_broker_mc_not_found"]


def test_boundary_stage_transition_authorized_when_clean_and_allowed(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    response = client.post("/api/loads/L1/stage", json={"stage": "Dispatched"}, headers=h("ops"))
    assert response.status_code == 200
    records = _shadow_records(db, "L1", "boundary_stage_transition")
    assert records[0]["decision"] == "AUTHORIZED"


def test_boundary_stage_transition_bypass_path_real_endpoint_still_blocks_disallowed(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    response = client.post("/api/loads/L1/stage", json={"stage": "Closed"}, headers=h("ops"))
    assert response.status_code == 409  # real transition gate is untouched
    records = _shadow_records(db, "L1", "boundary_stage_transition")
    assert records[0]["decision"] == "BLOCKED"
    assert records[0]["reason_codes"] == ["stage_transition_not_allowed"]


def test_boundary_stage_transition_tenant_isolation(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    client.post("/api/loads/L1/stage", json={"stage": "Dispatched"}, headers=h("ops"))
    client.post("/api/loads/LB/stage", json={"stage": "Dispatched"}, headers=h("foreign"))
    ta_records = [d for d in db.dispatch_authorization_evaluations.docs if d["tenant_id"] == TA]
    tb_records = [d for d in db.dispatch_authorization_evaluations.docs if d["tenant_id"] == TB]
    assert ta_records and all(r["load_id"] == "L1" for r in ta_records)
    assert tb_records and all(r["load_id"] == "LB" for r in tb_records)


def test_enforcement_flag_recorded_but_never_changes_behavior(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _not_found_verify)
    monkeypatch.setattr(server, "settings", replace(server.settings, dispatch_gate_enforced=True))
    db.load_passports.docs = [_ready_passport(db.loads.docs[0])]
    response = client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    assert response.status_code == 200  # BLOCKED shadow decision still never gates the real endpoint in PR1
    records = _shadow_records(db, "L1", "passport_authorization")
    assert records[0]["decision"] == "BLOCKED"
    assert records[0]["gate_enforced"] is True


def test_audit_event_is_written_for_a_shadow_evaluation(api):
    client, db = api
    db.load_passports.docs = [_ready_passport(db.loads.docs[0])]
    client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    events = [e for e in db.audit_events.docs if e.get("action") == "dispatch_authorization.shadow_evaluated"]
    assert len(events) == 1
    assert events[0]["entity_type"] == "dispatch_authorization_evaluation"


def test_shadow_persistence_failure_never_breaks_the_real_endpoint(api):
    client, db = api
    db.dispatch_authorization_evaluations.fail_insert = True
    db.load_passports.docs = [_ready_passport(db.loads.docs[0])]
    response = client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    assert response.status_code == 200
    assert db.dispatch_authorization_evaluations.docs == []
