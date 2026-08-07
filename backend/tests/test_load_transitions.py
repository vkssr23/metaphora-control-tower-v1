"""Independent tests for the canonical load transition policy and endpoint."""
import os
from types import SimpleNamespace
import pytest
os.environ.update({"JWT_SECRET":"isolated-test-only-secret-value-over-32-characters", "MONGO_URL":"mongodb://127.0.0.1:1/no-network-test", "DB_NAME":"isolated", "CORS_ORIGINS":"http://localhost:3000", "APP_ENV":"test", "ALLOW_SEED_ENDPOINT":"false"})
from app.domain.load_transitions import LOAD_TRANSITIONS, ORDERED_STAGES, transition_allowed
from app.schemas.loads import LoadStage, StageChange
from pydantic import ValidationError
from fastapi.testclient import TestClient
import server
VALID_TENANT = "ten_" + "a" * 32

class Collection:
    def __init__(self, docs=None): self.docs=list(docs or []); self.last_query=None; self.matched_count_override=None; self.read_override=None; self.fail_insert=False
    async def find_one(self, query, *args):
        if self.read_override is not None: return dict(self.read_override)
        return next((dict(d) for d in self.docs if all(d.get(k)==v for k,v in query.items())), None)
    async def update_one(self, query, update, **kwargs):
        self.last_query=query
        matches=[doc for doc in self.docs if all(doc.get(k)==v for k,v in query.items())]
        matched=len(matches) if self.matched_count_override is None else self.matched_count_override
        if matched:
            for doc in matches[:1]:
                doc.update(update.get("$set", {}))
                for key in update.get("$unset", {}): doc.pop(key, None)
        return SimpleNamespace(matched_count=matched, modified_count=1 if matched else 0)
    async def insert_one(self, doc):
        if self.fail_insert: raise RuntimeError("private activity failure")
        self.docs.append(dict(doc))

class DB:
    def __init__(self, stage=None, origin=None):
        doc = {"id":"L1", "stage":stage.value, "tenant_id":VALID_TENANT} if stage is not None else None
        if doc is not None and origin is not None: doc["exception_origin_stage"] = origin.value
        self.loads=Collection([] if doc is None else [doc]); self.activity=Collection()

def endpoint(stage, origin=None):
    fake=DB(stage, origin); server.db=fake
    async def user(): return {"id":"U1", "name":"Authenticated Actor", "role":"operations", "tenant_id":VALID_TENANT}
    server.app.dependency_overrides[server.get_current_user]=user
    return TestClient(server.app), fake

def test_every_forward_transition_and_same_stage_are_allowed():
    for current, requested in zip(ORDERED_STAGES, ORDERED_STAGES[1:]):
        assert transition_allowed(current, requested)
        assert transition_allowed(current, current)

def test_no_stage_skipping_or_backwards_transitions():
    for i, current in enumerate(ORDERED_STAGES):
        for j, requested in enumerate(ORDERED_STAGES):
            expected = i == j or j == i + 1
            assert transition_allowed(current, requested) is expected

def test_exception_is_one_way_and_reachable_from_active_stages():
    for stage in ORDERED_STAGES[:-1]: assert LoadStage.EXCEPTION in LOAD_TRANSITIONS[stage]
    assert not LOAD_TRANSITIONS[LoadStage.EXCEPTION]

def test_stage_request_rejects_unknown_and_actor_fields():
    with pytest.raises(ValidationError): StageChange.model_validate({"stage":"Unknown"})
    with pytest.raises(ValidationError): StageChange.model_validate({"stage":"Assigned", "updated_by":"spoof"})

@pytest.mark.parametrize("current,requested", [(a,b) for a in LoadStage for b in LoadStage])
def test_endpoint_enforces_every_stage_pair(current, requested):
    client, fake = endpoint(current)
    response=client.post("/api/loads/L1/stage", json={"stage":requested.value, "notes":"test"})
    allowed=transition_allowed(current, requested)
    assert response.status_code == (200 if allowed else 409)
    if current == requested:
        assert fake.activity.docs == []
    elif allowed:
        assert fake.loads.docs[0]["stage"] == requested.value
        assert fake.activity.docs[0]["updated_by"] == "Authenticated Actor"

def test_endpoint_unknown_stage_actor_spoof_and_missing_load():
    client, _ = endpoint(LoadStage.BOOKED)
    assert client.post("/api/loads/L1/stage", json={"stage":"Unknown"}).status_code == 422
    assert client.post("/api/loads/L1/stage", json={"stage":"Assigned", "updated_by":"spoof"}).status_code == 422
    client, _ = endpoint(None)
    assert client.post("/api/loads/L1/stage", json={"stage":"Assigned"}).status_code == 404

def test_exception_entry_and_origin_bound_recovery():
    client, fake = endpoint(LoadStage.IN_TRANSIT)
    assert client.post("/api/loads/L1/stage", json={"stage":"Exception", "notes":"issue"}).status_code == 200
    assert fake.loads.docs[0]["exception_origin_stage"] == "In Transit"
    assert fake.loads.last_query == {"id":"L1","stage":"In Transit","tenant_id":VALID_TENANT}
    assert fake.activity.docs[-1]["updated_by"] == "Authenticated Actor"

    client, fake = endpoint(LoadStage.EXCEPTION, LoadStage.IN_TRANSIT)
    assert client.post("/api/loads/L1/stage", json={"stage":"Delivered"}).status_code == 409
    assert client.post("/api/loads/L1/stage", json={"stage":"In Transit", "notes":"resolved"}).status_code == 200
    assert fake.loads.last_query == {"id":"L1","stage":"Exception","exception_origin_stage":"In Transit","tenant_id":VALID_TENANT}
    assert fake.loads.docs[0]["stage"] == "In Transit"
    assert "exception_origin_stage" not in fake.loads.docs[0]
    assert fake.activity.docs[-1]["old_status"] == "Exception"

def test_exception_without_origin_requires_remediation_and_origin_is_protected():
    client, _ = endpoint(LoadStage.EXCEPTION)
    assert client.post("/api/loads/L1/stage", json={"stage":"In Transit"}).status_code == 409
    assert client.put("/api/loads/L1", json={"exception_origin_stage":"Booked"}).status_code == 422

def test_two_stale_transitions_allow_only_first_writer_and_no_lost_race_activity():
    client, fake=endpoint(LoadStage.BOOKED)
    fake.loads.read_override={"id":"L1","stage":"Booked"}
    assert client.post("/api/loads/L1/stage", json={"stage":"Assigned"}).status_code==200
    assert client.post("/api/loads/L1/stage", json={"stage":"Assigned"}).status_code==409
    assert len(fake.activity.docs)==1

def test_exception_entry_recovery_and_origin_change_races_return_409_without_activity():
    client, fake=endpoint(LoadStage.IN_TRANSIT); fake.loads.matched_count_override=0
    assert client.post("/api/loads/L1/stage", json={"stage":"Exception"}).status_code==409
    assert fake.activity.docs==[]
    client, fake=endpoint(LoadStage.EXCEPTION, LoadStage.IN_TRANSIT); fake.loads.matched_count_override=0
    assert client.post("/api/loads/L1/stage", json={"stage":"In Transit"}).status_code==409
    assert fake.activity.docs==[]

def test_stage_activity_failure_returns_success_after_primary_write(caplog):
    client, fake=endpoint(LoadStage.BOOKED); fake.activity.fail_insert=True
    response=client.post("/api/loads/L1/stage", json={"stage":"Assigned"})
    assert response.status_code==200 and fake.loads.docs[0]["stage"]=="Assigned"
    assert "Activity logging failed after successful primary write" in caplog.text
