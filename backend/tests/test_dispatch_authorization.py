"""PR1: pure canonical evaluator, idempotent append-only store, and the two
shadow-evaluation integration points (passport authorization, dispatch
boundary stage transition). Covers tri-state precedence including Party
Verification / Execution Eligibility authority inputs, Verify failure/
timeout, tenant isolation, idempotency via deterministic _id, changed
evidence producing a new record even with an unchanged verdict, the exact
dispatch-boundary scope (including exception entry/recovery), both bypass
paths, latency-bounded shadow evaluation, and zero behavior change (PR1
has no enforcement flag at all).
"""
import asyncio
import copy
import os
import time

os.environ.update({"JWT_SECRET": "isolated-test-only-secret-value-over-32-characters", "MONGO_URL": "mongodb://127.0.0.1:1/no-network-test", "DB_NAME": "isolated", "CORS_ORIGINS": "http://localhost:3000", "APP_ENV": "test", "ALLOW_SEED_ENDPOINT": "false"})

import pytest

import app.infrastructure.party_verification_client as party_verification_client
import server
from app.domain import dispatch_authorization as da
from app.domain.load_passports import bounded_load_snapshot
from app.infrastructure import dispatch_authorization_store as store
from app.schemas.loads import LoadStage
from test_rate_confirmation_routes import DOC, FakeDB, LOAD, TA, TB, USERS, h

# ---------------------------------------------------------------------------
# Section A: pure canonical evaluator
# ---------------------------------------------------------------------------

def test_negative_wins_over_review_precedence():
    outcome = da.evaluate({"verify_broker_mc_not_found"}, {"verify_unavailable", "evidence_missing"})
    assert outcome.decision == da.DispatchDecision.BLOCKED
    assert outcome.reason_codes == ("verify_broker_mc_not_found",)


def test_review_required_when_only_unknowns():
    outcome = da.evaluate(set(), {"verify_not_attempted"})
    assert outcome.decision == da.DispatchDecision.REVIEW_REQUIRED


def test_authorized_when_clean():
    outcome = da.evaluate(set(), set())
    assert outcome.decision == da.DispatchDecision.AUTHORIZED
    assert outcome.reason_codes == ()


@pytest.mark.parametrize("verify_result,expected_negatives,expected_reviews", [
    (None, set(), {"verify_not_attempted"}),
    ({"status": "unavailable"}, set(), {"verify_unavailable"}),
    ({"status": "timed_out"}, set(), {"verify_timed_out"}),
    ({"status": "not_found"}, {"verify_broker_mc_not_found"}, set()),
    ({"status": "weird"}, set(), {"evidence_malformed"}),
    # authority: ACTIVE positive; INACTIVE/OUT_OF_SERVICE/NOT_AUTHORIZED blocking; UNKNOWN/missing review; anything else malformed
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Green"}, set(), set()),
    ({"status": "ok", "broker_authority_status": "UNKNOWN", "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Green"}, set(), {"verify_broker_authority_unknown"}),
    ({"status": "ok", "broker_authority_status": None, "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Green"}, set(), {"verify_broker_authority_unknown"}),
    ({"status": "ok", "broker_authority_status": "INACTIVE", "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Green"}, {"verify_broker_authority_inactive"}, set()),
    ({"status": "ok", "broker_authority_status": "OUT_OF_SERVICE", "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Green"}, {"verify_broker_authority_inactive"}, set()),
    ({"status": "ok", "broker_authority_status": "NOT_AUTHORIZED", "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Green"}, {"verify_broker_authority_inactive"}, set()),
    ({"status": "ok", "broker_authority_status": "SOMETHING_NEW", "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Green"}, set(), {"evidence_malformed"}),
    # bond requirement: NOT_REQUIRED positive; REQUIRED evaluates on_file; UNKNOWN/missing review; anything else malformed
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": None, "risk_level": "Green"}, set(), {"verify_bond_insurance_requirement_unknown"}),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "REQUIRED", "bond_insurance_on_file": "PRESENT", "risk_level": "Green"}, set(), set()),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "REQUIRED", "bond_insurance_on_file": "ABSENT", "risk_level": "Green"}, {"verify_bond_insurance_absent"}, set()),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "REQUIRED", "bond_insurance_on_file": None, "risk_level": "Green"}, set(), {"verify_bond_insurance_on_file_unknown"}),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "REQUIRED", "bond_insurance_on_file": "WEIRD", "risk_level": "Green"}, set(), {"evidence_malformed"}),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "SOMETHING_ELSE", "risk_level": "Green"}, set(), {"evidence_malformed"}),
    # risk: Green positive; Yellow review; Red blocking; missing/unexpected malformed
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Yellow"}, set(), {"verify_fraud_risk_yellow"}),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Red"}, {"verify_fraud_risk_red"}, set()),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "NOT_REQUIRED"}, set(), {"evidence_malformed"}),
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Purple"}, set(), {"evidence_malformed"}),
    # flags
    ({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Green", "flags": [{"code": "SHARED_CONTACT_REVOKED_ENTITY"}]}, {"verify_shared_contact_revoked_entity"}, set()),
])
def test_verify_reason_codes_tri_state_vocabulary(verify_result, expected_negatives, expected_reviews):
    negatives, reviews = da.verify_reason_codes(verify_result)
    assert negatives == expected_negatives
    assert reviews == expected_reviews


def test_bond_insurance_required_unknown_is_never_silently_ignored():
    # Regression: previously an UNKNOWN/None/missing bond requirement
    # produced no reason code at all, silently discarding tri-state
    # evidence instead of surfacing it as REVIEW_REQUIRED.
    for required in (None, "", "UNKNOWN"):
        negatives, reviews = da.verify_reason_codes({"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": required, "risk_level": "Green"})
        assert negatives == set()
        assert "verify_bond_insurance_requirement_unknown" in reviews


@pytest.mark.parametrize("status,expected", [
    ("draft", (set(), {"passport_not_yet_approved"})),
    ("review_pending", (set(), {"passport_not_yet_approved"})),
    ("blocked", ({"passport_blocked"}, set())),
    ("revoked", ({"passport_revoked"}, set())),
])
def test_passport_authorization_reason_codes_pending_states_are_review_not_blocked(status, expected):
    negatives, reviews = da.passport_authorization_reason_codes({"status": status}, None)
    assert negatives == expected[0]
    assert reviews == expected[1]


def test_passport_authorization_readiness_incomplete_is_review_not_negative():
    # Regression: a False readiness boolean bundles many pending/
    # insufficient-evidence reasons (unsatisfied checkpoints, missing
    # profitability snapshot, incomplete assignment, ...) - none of them
    # are an explicit denial, so this must never collapse to BLOCKED.
    negatives, reviews = da.passport_authorization_reason_codes(
        {"status": "approved", "approved_version": 2, "version": 2}, {"ready_for_pickup_authorization": False})
    assert negatives == set()
    assert reviews == {"passport_readiness_incomplete"}


def test_passport_authorization_reason_codes_missing_passport_is_review():
    negatives, reviews = da.passport_authorization_reason_codes(None, None)
    assert negatives == set() and reviews == {"evidence_missing"}


def test_passport_authorization_reason_codes_version_mismatch_is_review():
    negatives, reviews = da.passport_authorization_reason_codes(
        {"status": "approved", "approved_version": 2, "version": 3}, {"ready_for_pickup_authorization": True})
    assert negatives == set() and reviews == {"passport_version_mismatch"}


@pytest.mark.parametrize("case,expected_negatives,expected_reviews", [
    (None, set(), {"party_verification_missing"}),
    ({"status": "cleared"}, set(), set()),
    ({"status": "blocked"}, {"party_verification_blocked"}, set()),
    ({"status": "revoked"}, {"party_verification_blocked"}, set()),
    ({"status": "review_pending"}, set(), {"party_verification_not_cleared"}),
    ({"status": "findings_open"}, set(), {"party_verification_not_cleared"}),
    ({"status": "expired"}, set(), {"party_verification_not_cleared"}),
    # actual evidence, not only the top-level status
    ({"status": "cleared", "blocking_reasons": ["missing_broker_identifier"]}, {"party_verification_blocked"}, set()),
    ({"status": "cleared", "risk_summary": {"blocking_signal_count": 1}}, {"party_verification_blocked"}, set()),
    ({"status": "cleared", "findings": [{"status": "open", "blocking": True}]}, {"party_verification_blocked"}, set()),
    ({"status": "cleared", "findings": [{"status": "open", "blocking": False}]}, set(), set()),
    ({"status": "cleared", "findings": [{"status": "resolved", "blocking": True}]}, set(), set()),
])
def test_party_verification_reason_codes(case, expected_negatives, expected_reviews):
    negatives, reviews = da.party_verification_reason_codes(case)
    assert negatives == expected_negatives and reviews == expected_reviews


def test_party_verification_reason_codes_ambiguous_is_review_not_an_arbitrary_pick():
    negatives, reviews = da.party_verification_reason_codes({"status": "cleared"}, ambiguous=True)
    assert negatives == set() and reviews == {"party_verification_ambiguous"}


@pytest.mark.parametrize("case,expected_negatives,expected_reviews", [
    (None, set(), {"execution_eligibility_missing"}),
    ({"status": "eligible", "verdict": "eligible"}, set(), set()),
    ({"status": "blocked"}, {"execution_eligibility_blocked"}, set()),
    ({"status": "revoked"}, {"execution_eligibility_blocked"}, set()),
    ({"status": "review_required", "verdict": "review_required"}, set(), {"execution_eligibility_not_eligible"}),
    # actual evidence, not only the top-level status
    ({"status": "eligible", "verdict": "blocked"}, {"execution_eligibility_blocked"}, set()),
    ({"status": "eligible", "verdict": "eligible", "blocking_reasons": ["driver_assignment"]}, {"execution_eligibility_blocked"}, set()),
    ({"status": "eligible", "verdict": "eligible", "checks": [{"type": "driver_assignment", "result": "fail"}]}, {"execution_eligibility_blocked"}, set()),
    ({"status": "eligible", "verdict": "eligible", "checks": [{"type": "hos_readiness", "result": "warning"}]}, set(), set()),
])
def test_execution_eligibility_reason_codes(case, expected_negatives, expected_reviews):
    negatives, reviews = da.execution_eligibility_reason_codes(case)
    assert negatives == expected_negatives and reviews == expected_reviews


def test_execution_eligibility_reason_codes_ambiguous_is_review_not_an_arbitrary_pick():
    negatives, reviews = da.execution_eligibility_reason_codes({"status": "eligible", "verdict": "eligible"}, ambiguous=True)
    assert negatives == set() and reviews == {"execution_eligibility_ambiguous"}


def test_evaluate_passport_authorization_authorized_requires_every_authority_positive():
    clean_verify = {"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Green"}
    approved = {"status": "approved", "approved_version": 1, "version": 1}
    ready = {"ready_for_pickup_authorization": True}
    # party verification missing -> not AUTHORIZED even though everything else is clean
    outcome = da.evaluate_passport_authorization(verify_result=clean_verify, passport=approved, readiness=ready, party_verification_case=None)
    assert outcome.decision == da.DispatchDecision.REVIEW_REQUIRED
    assert outcome.reason_codes == ("party_verification_missing",)
    # every authority affirmatively positive -> AUTHORIZED
    outcome = da.evaluate_passport_authorization(verify_result=clean_verify, passport=approved, readiness=ready, party_verification_case={"status": "cleared"})
    assert outcome.decision == da.DispatchDecision.AUTHORIZED
    # ambiguous party verification -> not AUTHORIZED, distinct reason code
    outcome = da.evaluate_passport_authorization(verify_result=clean_verify, passport=approved, readiness=ready,
                                                  party_verification_case=None, party_verification_ambiguous=True)
    assert outcome.decision == da.DispatchDecision.REVIEW_REQUIRED
    assert outcome.reason_codes == ("party_verification_ambiguous",)


def test_evaluate_boundary_stage_transition_requires_execution_eligibility_too():
    clean_verify = {"status": "ok", "broker_authority_status": "ACTIVE", "bond_insurance_required": "NOT_REQUIRED", "risk_level": "Green"}
    cleared_party = {"status": "cleared"}
    outcome = da.evaluate_boundary_stage_transition(
        verify_result=clean_verify, current_stage="Assigned", requested_stage="Dispatched", transition_is_allowed=True,
        party_verification_case=cleared_party, execution_eligibility_case=None)
    assert outcome.decision == da.DispatchDecision.REVIEW_REQUIRED
    assert outcome.reason_codes == ("execution_eligibility_missing",)
    outcome = da.evaluate_boundary_stage_transition(
        verify_result=clean_verify, current_stage="Assigned", requested_stage="Dispatched", transition_is_allowed=True,
        party_verification_case=cleared_party, execution_eligibility_case={"status": "eligible", "verdict": "eligible"})
    assert outcome.decision == da.DispatchDecision.AUTHORIZED


def test_evaluate_boundary_stage_transition_negative_still_blocks_even_when_transition_allowed():
    outcome = da.evaluate_boundary_stage_transition(
        verify_result={"status": "not_found"}, current_stage="Assigned", requested_stage="Dispatched", transition_is_allowed=True,
        party_verification_case={"status": "cleared"}, execution_eligibility_case={"status": "eligible"})
    assert outcome.decision == da.DispatchDecision.BLOCKED
    assert outcome.reason_codes == ("verify_broker_mc_not_found",)


# ---------------------------------------------------------------------------
# Section A2: the named dispatch-boundary constant
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("current,requested,expected", [
    (LoadStage.ASSIGNED, LoadStage.DISPATCHED, True),
    (LoadStage.BOOKED, LoadStage.ASSIGNED, False),
    (LoadStage.DISPATCHED, LoadStage.EXCEPTION, False),  # exception entry from Dispatched: not the boundary
    (LoadStage.EXCEPTION, LoadStage.DISPATCHED, False),  # exception recovery back into Dispatched: not the boundary
    (LoadStage.ASSIGNED, LoadStage.EXCEPTION, False),
    (LoadStage.ASSIGNED, LoadStage.ASSIGNED, False),
    (None, LoadStage.DISPATCHED, False),
])
def test_is_dispatch_boundary_transition(current, requested, expected):
    assert da.is_dispatch_boundary_transition(current, requested) is expected


def test_dispatch_boundary_transition_constant_is_assigned_to_dispatched():
    assert da.DISPATCH_BOUNDARY_TRANSITION == (LoadStage.ASSIGNED, LoadStage.DISPATCHED)


# ---------------------------------------------------------------------------
# Section A3: latest-case selection - deterministic tenant+load query,
# sorted, bounded to two records, and ambiguous (not an arbitrary find_one()
# pick) when more than one record matches.
# ---------------------------------------------------------------------------

class _RecordingCursor:
    def __init__(self, docs):
        self._docs = docs
        self.sort_spec = None
        self.to_list_length = None

    def sort(self, spec):
        self.sort_spec = spec
        return self

    async def to_list(self, length):
        self.to_list_length = length
        return self._docs[:length]


class _RecordingCaseCollection:
    def __init__(self, docs):
        self._docs = docs
        self.last_query = None
        self.last_cursor = None

    def find(self, query, *args, **kwargs):
        self.last_query = query
        matched = [d for d in self._docs if all(d.get(k) == v for k, v in query.items())]
        self.last_cursor = _RecordingCursor(matched)
        return self.last_cursor


@pytest.mark.anyio
async def test_latest_case_queries_tenant_and_load_sorted_and_bounded_to_two():
    from app.dispatch_authorization_shadow import _latest_case
    collection = _RecordingCaseCollection([{"id": "PVC1", "tenant_id": TA, "load_id": "L1", "status": "cleared"}])
    case, ambiguous = await _latest_case(collection, USERS["ops"], "L1")
    assert ambiguous is False and case["id"] == "PVC1"
    assert collection.last_query == {"tenant_id": TA, "load_id": "L1"}
    assert collection.last_cursor.sort_spec == [("updated_at", -1), ("version", -1), ("id", -1)]
    assert collection.last_cursor.to_list_length == 2


@pytest.mark.anyio
async def test_latest_case_no_match_is_missing_not_ambiguous():
    from app.dispatch_authorization_shadow import _latest_case
    case, ambiguous = await _latest_case(_RecordingCaseCollection([]), USERS["ops"], "L1")
    assert case is None and ambiguous is False


@pytest.mark.anyio
async def test_latest_case_more_than_one_match_is_ambiguous_not_an_arbitrary_pick():
    from app.dispatch_authorization_shadow import _latest_case
    collection = _RecordingCaseCollection([
        {"id": "PVC1", "tenant_id": TA, "load_id": "L1", "status": "cleared", "updated_at": "2026-01-01"},
        {"id": "PVC2", "tenant_id": TA, "load_id": "L1", "status": "blocked", "updated_at": "2026-01-02"},
    ])
    case, ambiguous = await _latest_case(collection, USERS["ops"], "L1")
    assert case is None and ambiguous is True


@pytest.mark.anyio
async def test_latest_case_isolates_by_tenant():
    from app.dispatch_authorization_shadow import _latest_case
    collection = _RecordingCaseCollection([
        {"id": "PVC1", "tenant_id": TA, "load_id": "L1", "status": "cleared"},
        {"id": "PVC2", "tenant_id": TB, "load_id": "L1", "status": "blocked"},
    ])
    case, ambiguous = await _latest_case(collection, USERS["ops"], "L1")
    assert ambiguous is False and case["id"] == "PVC1"  # tenant B's same-load-id case is invisible to tenant A


# ---------------------------------------------------------------------------
# Section B: append-only, idempotent store (deterministic _id, not the
# never-auto-applied manifest index)
# ---------------------------------------------------------------------------

class _RealMongoIdCollection:
    """Minimal fake enforcing Mongo's own default _id uniqueness - no
    custom index required, matching the real correctness mechanism."""
    def __init__(self):
        self.docs = []
        self.insert_calls = 0

    async def insert_one(self, doc):
        self.insert_calls += 1
        if any(d["_id"] == doc["_id"] for d in self.docs):
            raise RuntimeError("E11000 duplicate key error collection: dispatch_authorization_evaluations index: _id_")
        self.docs.append(dict(doc))

    async def find_one(self, query, *args):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None


def _outcome(decision="AUTHORIZED", codes=()):
    return da.DispatchOutcome(da.DispatchDecision(decision), tuple(codes))


@pytest.mark.anyio
async def test_record_evaluation_is_idempotent_via_deterministic_id_not_the_manifest_index():
    collection = _RealMongoIdCollection()
    kwargs = dict(tenant_id=TA, load_id="L1", subject="passport_authorization", outcome=_outcome(),
                  load_version="2026-01-01T00:00:00Z", sources=[{"source": "load", "id": "L1", "version": "v1"}],
                  evidence_freshness="current", mode="SHADOW")
    first = await store.record_evaluation(collection, **kwargs)
    second = await store.record_evaluation(collection, **kwargs)
    assert first["id"] == second["id"]
    assert first["input_hash"] == second["input_hash"]
    assert len(collection.docs) == 1
    assert collection.insert_calls == 2  # the second attempt raced _id and was replayed, not skipped
    assert "_id" not in first and "_id" not in second


@pytest.mark.anyio
async def test_record_evaluation_distinguishes_stale_load_versions():
    collection = _RealMongoIdCollection()
    base = dict(tenant_id=TA, load_id="L1", subject="passport_authorization", outcome=_outcome(),
                sources=[], evidence_freshness="current", mode="SHADOW")
    first = await store.record_evaluation(collection, load_version="v1", **base)
    second = await store.record_evaluation(collection, load_version="v2", **base)
    assert first["id"] != second["id"]
    assert len(collection.docs) == 2


@pytest.mark.anyio
async def test_record_evaluation_changed_evidence_creates_new_record_even_with_unchanged_verdict():
    collection = _RealMongoIdCollection()
    base = dict(tenant_id=TA, load_id="L1", subject="boundary_stage_transition", outcome=_outcome("AUTHORIZED"),
                load_version="v1", evidence_freshness="current", mode="SHADOW")
    first = await store.record_evaluation(collection, sources=[{"source": "party_verification_case", "id": "PVC1", "version": "1"}], **base)
    second = await store.record_evaluation(collection, sources=[{"source": "party_verification_case", "id": "PVC1", "version": "2"}], **base)
    assert first["decision"] == second["decision"] == "AUTHORIZED"
    assert first["id"] != second["id"]
    assert len(collection.docs) == 2
    # freshness changing alone, with everything else equal, must also mint a new record
    third = await store.record_evaluation(collection, sources=[{"source": "party_verification_case", "id": "PVC1", "version": "2"}],
                                          tenant_id=TA, load_id="L1", subject="boundary_stage_transition", outcome=_outcome("AUTHORIZED"),
                                          load_version="v1", evidence_freshness="unavailable", mode="SHADOW")
    assert third["id"] != second["id"]
    assert len(collection.docs) == 3


@pytest.mark.anyio
async def test_record_evaluation_source_order_does_not_affect_the_idempotency_identity():
    collection = _RealMongoIdCollection()
    base = dict(tenant_id=TA, load_id="L1", subject="passport_authorization", outcome=_outcome(),
                load_version="v1", evidence_freshness="current", mode="SHADOW")
    a = {"source": "load", "id": "L1", "version": "v1"}
    b = {"source": "load_passport", "id": "P1", "version": "1"}
    first = await store.record_evaluation(collection, sources=[a, b], **base)
    second = await store.record_evaluation(collection, sources=[b, a], **base)
    assert first["id"] == second["id"]
    assert len(collection.docs) == 1


@pytest.mark.anyio
async def test_record_evaluation_never_leaks_across_tenants():
    collection = _RealMongoIdCollection()
    base = dict(load_id="L1", subject="passport_authorization", outcome=_outcome(),
                load_version="v1", sources=[], evidence_freshness="current", mode="SHADOW")
    a = await store.record_evaluation(collection, tenant_id=TA, **base)
    b = await store.record_evaluation(collection, tenant_id=TB, **base)
    assert a["id"] != b["id"]
    assert {d["tenant_id"] for d in collection.docs} == {TA, TB}


@pytest.mark.anyio
async def test_record_evaluation_never_stores_evidence_contents():
    collection = _RealMongoIdCollection()
    doc = await store.record_evaluation(
        collection, tenant_id=TA, load_id="L1", subject="passport_authorization",
        outcome=_outcome("BLOCKED", ["verify_broker_authority_inactive"]), load_version="v1",
        sources=[{"source": "load", "id": "L1", "version": "v1"}], evidence_freshness="current", mode="SHADOW")
    allowed = {"id", "tenant_id", "load_id", "subject", "decision", "evaluator_version", "load_version",
               "reason_codes", "sources", "evidence_freshness", "mode", "evaluated_at", "input_hash"}
    assert set(doc) == allowed


# ---------------------------------------------------------------------------
# Section C: shadow-evaluation integration, exercised through the real HTTP
# endpoints.
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


async def _not_found_verify(settings, rate):
    return {"status": "not_found"}


def _cleared_party_case(load_id="L1", tenant=TA):
    return {"id": "PVC1", "tenant_id": tenant, "load_id": load_id, "version": 1, "status": "cleared"}


def _eligible_execution_case(load_id="L1", tenant=TA):
    return {"id": "EEC1", "tenant_id": tenant, "load_id": load_id, "version": 1, "status": "eligible", "verdict": "eligible"}


@pytest.fixture
def api(monkeypatch):
    from fastapi import Header, HTTPException
    from fastapi.testclient import TestClient

    db = FakeDB()
    for name in ("dispatch_authorization_evaluations", "party_verification_cases", "execution_eligibility_cases"):
        setattr(db, name, type(db.audit_events)(name, db.events))
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


def test_passport_authorization_authorized_only_when_every_authority_is_positive(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    db.load_passports.docs = [_ready_passport(db.loads.docs[0])]
    # no party verification case yet -> not AUTHORIZED despite everything else clean
    response = client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    assert response.status_code == 200  # real gate is unaffected
    records = _shadow_records(db, "L1", "passport_authorization")
    assert records[0]["decision"] == "REVIEW_REQUIRED"
    assert records[0]["reason_codes"] == ["party_verification_missing"]
    # now cleared -> AUTHORIZED
    db.party_verification_cases.docs = [_cleared_party_case()]
    db.load_passports.docs = [_ready_passport(db.loads.docs[0])]
    client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    records = _shadow_records(db, "L1", "passport_authorization")
    assert records[-1]["decision"] == "AUTHORIZED"


def test_passport_authorization_bypass_path_real_endpoint_still_blocks_unapproved(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    db.party_verification_cases.docs = [_cleared_party_case()]
    passport = _ready_passport(db.loads.docs[0])
    passport["status"] = "blocked"
    db.load_passports.docs = [passport]
    response = client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    assert response.status_code == 409  # real gate is untouched by the shadow evaluator
    records = _shadow_records(db, "L1", "passport_authorization")
    assert records[0]["decision"] == "BLOCKED"
    assert records[0]["reason_codes"] == ["passport_blocked"]


def test_passport_authorization_pending_status_is_review_required_not_blocked(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    db.party_verification_cases.docs = [_cleared_party_case()]
    passport = _ready_passport(db.loads.docs[0])
    passport["status"] = "draft"
    db.load_passports.docs = [passport]
    response = client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    assert response.status_code == 409
    records = _shadow_records(db, "L1", "passport_authorization")
    assert records[0]["decision"] == "REVIEW_REQUIRED"
    assert records[0]["reason_codes"] == ["passport_not_yet_approved"]


def test_passport_authorization_verify_explicit_negative_blocks_even_when_everything_else_clean(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _not_found_verify)
    db.party_verification_cases.docs = [_cleared_party_case()]
    db.load_passports.docs = [_ready_passport(db.loads.docs[0])]
    response = client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    assert response.status_code == 200  # real endpoint has no Verify gate today - unaffected
    records = _shadow_records(db, "L1", "passport_authorization")
    assert records[0]["decision"] == "BLOCKED"
    assert records[0]["reason_codes"] == ["verify_broker_mc_not_found"]


def test_boundary_only_evaluates_the_exact_dispatch_boundary_transition(monkeypatch, api):
    client, db = api
    calls = []

    async def _counting_verify(settings, rate):
        calls.append(1)
        return CLEAN_VERIFY
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _counting_verify)

    # Booked -> Assigned: ordinary, non-boundary transition. No Verify call, no shadow record.
    db.loads.docs[0]["stage"] = "Booked"
    response = client.post("/api/loads/L1/stage", json={"stage": "Assigned"}, headers=h("ops"))
    assert response.status_code == 200
    assert calls == []
    assert _shadow_records(db, "L1", "boundary_stage_transition") == []

    # Assigned -> Dispatched: the dispatch boundary. Verify is called and a record is written.
    response = client.post("/api/loads/L1/stage", json={"stage": "Dispatched"}, headers=h("ops"))
    assert response.status_code == 200
    assert len(calls) == 1
    assert len(_shadow_records(db, "L1", "boundary_stage_transition")) == 1


def test_boundary_exception_entry_and_recovery_are_excluded_from_the_boundary(monkeypatch, api):
    client, db = api
    calls = []

    async def _counting_verify(settings, rate):
        calls.append(1)
        return CLEAN_VERIFY
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _counting_verify)

    db.loads.docs[0]["stage"] = "Dispatched"
    response = client.post("/api/loads/L1/stage", json={"stage": "Exception"}, headers=h("ops"))
    assert response.status_code == 200  # entering exception is a normal, allowed transition
    assert calls == []
    assert _shadow_records(db, "L1", "boundary_stage_transition") == []

    db.loads.docs[0]["stage"] = "Exception"
    db.loads.docs[0]["exception_origin_stage"] = "Dispatched"
    response = client.post("/api/loads/L1/stage", json={"stage": "Dispatched"}, headers=h("ops"))
    assert response.status_code == 200  # recovery back to the origin is allowed
    assert calls == []
    assert _shadow_records(db, "L1", "boundary_stage_transition") == []


def test_boundary_bypass_path_real_endpoint_still_blocks_disallowed_transition(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    response = client.post("/api/loads/L1/stage", json={"stage": "Closed"}, headers=h("ops"))
    assert response.status_code == 409  # real transition gate is untouched; not the boundary anyway
    assert _shadow_records(db, "L1", "boundary_stage_transition") == []


def test_boundary_authorized_only_when_party_and_execution_authorities_both_positive(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    db.party_verification_cases.docs = [_cleared_party_case()]
    # execution eligibility missing -> not AUTHORIZED
    response = client.post("/api/loads/L1/stage", json={"stage": "Dispatched"}, headers=h("ops"))
    assert response.status_code == 200
    records = _shadow_records(db, "L1", "boundary_stage_transition")
    assert records[0]["decision"] == "REVIEW_REQUIRED"
    assert "execution_eligibility_missing" in records[0]["reason_codes"]


def test_boundary_tenant_isolation(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    db.party_verification_cases.docs = [_cleared_party_case(), _cleared_party_case("LB", TB)]
    db.execution_eligibility_cases.docs = [_eligible_execution_case(), _eligible_execution_case("LB", TB)]
    client.post("/api/loads/L1/stage", json={"stage": "Dispatched"}, headers=h("ops"))
    client.post("/api/loads/LB/stage", json={"stage": "Dispatched"}, headers=h("foreign"))
    ta_records = [d for d in db.dispatch_authorization_evaluations.docs if d["tenant_id"] == TA]
    tb_records = [d for d in db.dispatch_authorization_evaluations.docs if d["tenant_id"] == TB]
    assert ta_records and all(r["load_id"] == "L1" for r in ta_records)
    assert tb_records and all(r["load_id"] == "LB" for r in tb_records)
    assert ta_records[0]["decision"] == "AUTHORIZED" and tb_records[0]["decision"] == "AUTHORIZED"


def test_boundary_duplicate_party_verification_cases_are_ambiguous_not_arbitrarily_selected(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    # Simulates a production database without the uniqueness index this
    # collection is supposed to have - two cases exist for the same
    # tenant+load.
    db.party_verification_cases.docs = [_cleared_party_case(), {**_cleared_party_case(), "id": "PVC2", "status": "blocked"}]
    db.execution_eligibility_cases.docs = [_eligible_execution_case()]
    response = client.post("/api/loads/L1/stage", json={"stage": "Dispatched"}, headers=h("ops"))
    assert response.status_code == 200  # real endpoint still unaffected
    records = _shadow_records(db, "L1", "boundary_stage_transition")
    assert records[0]["decision"] == "REVIEW_REQUIRED"
    assert records[0]["reason_codes"] == ["party_verification_ambiguous"]
    assert not any(s["source"] == "party_verification_case" for s in records[0]["sources"])  # no arbitrary pick recorded either


def test_boundary_ambiguity_is_tenant_scoped(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
    db.party_verification_cases.docs = [_cleared_party_case(), {**_cleared_party_case(), "id": "PVC2"}, _cleared_party_case("LB", TB)]
    db.execution_eligibility_cases.docs = [_eligible_execution_case(), _eligible_execution_case("LB", TB)]
    client.post("/api/loads/L1/stage", json={"stage": "Dispatched"}, headers=h("ops"))
    client.post("/api/loads/LB/stage", json={"stage": "Dispatched"}, headers=h("foreign"))
    ta_records = _shadow_records(db, "L1", "boundary_stage_transition")
    tb_records = _shadow_records(db, "LB", "boundary_stage_transition")
    assert ta_records[0]["decision"] == "REVIEW_REQUIRED" and "party_verification_ambiguous" in ta_records[0]["reason_codes"]
    assert tb_records[0]["decision"] == "AUTHORIZED"  # tenant B's single case is unaffected by tenant A's duplicate


def test_shadow_evaluation_is_latency_bounded_and_never_gates_the_response(monkeypatch, api):
    client, db = api

    async def _hanging_verify(settings, rate):
        await asyncio.sleep(3.0)  # much longer than SHADOW_VERIFY_TIMEOUT_SECONDS and than Verify's own 5s default
        return CLEAN_VERIFY
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _hanging_verify)
    db.party_verification_cases.docs = [_cleared_party_case()]
    db.load_passports.docs = [_ready_passport(db.loads.docs[0])]

    started = time.monotonic()
    response = client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert elapsed < 2.5  # well under the 3s hang and the old 5s Verify default
    records = _shadow_records(db, "L1", "passport_authorization")
    assert records[0]["evidence_freshness"] == "timed_out"
    assert records[0]["reason_codes"] == ["verify_timed_out"]
    assert records[0]["decision"] == "REVIEW_REQUIRED"  # a timeout is unknown evidence, never a denial


def test_audit_event_is_written_for_a_shadow_evaluation(monkeypatch, api):
    client, db = api
    monkeypatch.setattr(party_verification_client, "fetch_broker_verification", _clean_verify)
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


def test_no_enforcement_flag_exists_anywhere_in_pr1(api):
    # PR1 has no enforcement gate at all - mode is always the constant SHADOW.
    assert not hasattr(server.settings, "dispatch_gate_enforced")
    client, db = api
    db.load_passports.docs = [_ready_passport(db.loads.docs[0])]
    response = client.post("/api/load-passports/lps_1/authorize-pickup", json={}, headers=h("owner"))
    assert response.status_code == 200
    records = _shadow_records(db, "L1", "passport_authorization")
    assert records[0]["mode"] == "SHADOW"
