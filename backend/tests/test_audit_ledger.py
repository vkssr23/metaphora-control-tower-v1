"""Isolated Security Patch 0D tests; fake collections only."""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

os.environ.update({"JWT_SECRET":"isolated-test-only-secret-value-over-32-characters", "MONGO_URL":"mongodb://127.0.0.1:1/no-network-test", "DB_NAME":"isolated", "CORS_ORIGINS":"http://localhost:3000", "APP_ENV":"test", "ALLOW_SEED_ENDPOINT":"false"})

import server
from app.audit import AUDIT_START_UNAVAILABLE, begin_audit
from app.domain.audit_events import build_event, incomplete_operations, integrity_hash, sanitize_summary, verify_integrity
from app.schemas.audit import AuditEntityType, AuditPhase
from test_tenant_isolation import FakeDB, TEN_A, TEN_B

USER_A = {"id":"UA", "email":"ACTOR@EXAMPLE.COM", "name":"Actor", "role":"owner", "tenant_id":TEN_A}


def test_event_is_server_controlled_deterministic_and_tamper_evident():
    event = build_event(user=USER_A, operation_id="op_fixed", phase=AuditPhase.STARTED,
                        action="load.updated", entity_type=AuditEntityType.LOAD, entity_id="L1",
                        changed_fields=["stage", "password"], previous={"stage":"Booked", "password":"no"})
    assert event["id"].startswith("aud_") and event["tenant_id"] == TEN_A
    assert event["actor_id"] == "UA" and event["actor_email"] == "actor@example.com"
    assert event["changed_fields"] == ["stage"] and event["previous_state_summary"] == {"stage":"Booked"}
    assert datetime.fromisoformat(event["occurred_at"]).tzinfo and verify_integrity(event)
    copy = dict(event); copy["_id"] = "mongo"; assert integrity_hash(copy) == event["integrity_hash"]
    copy["action"] = "load.deleted"; assert not verify_integrity(copy)


def test_sanitizer_removes_credentials_and_bounds_values():
    safe = sanitize_summary({"password":"x", "jwt_token":"x", "authorization":"x", "notes":"x"*1000,
                             "filename":"f"*500, "stage":"Booked", "url":"https://u:p@h/doc?q=secret"})
    assert safe == {"filename":"f"*256, "stage":"Booked"}


def test_audit_start_failure_is_sanitized_503_and_blocks_primary():
    db=FakeDB(); db.audit_events.fail_insert=True
    with pytest.raises(Exception) as exc:
        asyncio.run(begin_audit(db.audit_events, USER_A, "truck.created", AuditEntityType.TRUCK, "T1"))
    assert exc.value.status_code == 503 and exc.value.detail == AUDIT_START_UNAVAILABLE
    assert db.trucks.docs == []


@pytest.fixture
def api(monkeypatch):
    fake=FakeDB(); monkeypatch.setattr(server,"db",fake); server.app.dependency_overrides.clear()
    current = dict(USER_A)
    async def user(): return dict(current)
    server.app.dependency_overrides[server.get_current_user]=user
    yield TestClient(server.app), fake, current
    server.app.dependency_overrides.clear()


def test_mutation_started_precedes_primary_and_success_is_terminal(api):
    client, db, _=api
    response=client.post("/api/trucks",json={"truck_number":"T-1"})
    assert response.status_code==200
    assert [e["phase"] for e in db.audit_events.docs]==["started","succeeded"]
    assert db.audit_events.docs[0]["operation_id"]==db.audit_events.docs[1]["operation_id"]
    assert db.audit_events.docs[0]["tenant_id"]==db.trucks.docs[0]["tenant_id"]==TEN_A


def test_mutation_is_blocked_when_started_insert_fails(api):
    client, db, _=api; db.audit_events.fail_insert=True
    response=client.post("/api/trucks",json={"truck_number":"T-1"})
    assert response.status_code==503 and response.json()=={"detail":AUDIT_START_UNAVAILABLE}
    assert db.trucks.docs==[]


def test_read_api_role_and_tenant_scope(api):
    client, db, current=api
    for user, entity in ((USER_A,"A"),({**USER_A,"tenant_id":TEN_B,"id":"UB"},"B")):
        db.audit_events.docs.append(build_event(user=user,operation_id=f"op_{entity}",phase=AuditPhase.SUCCEEDED,
                                                action="load.created",entity_type=AuditEntityType.LOAD,entity_id=entity))
    response=client.get("/api/audit-events?limit=1")
    assert response.status_code==200 and [e["entity_id"] for e in response.json()]==["A"]
    assert db.audit_events.queries[-1]["tenant_id"]==TEN_A
    current["role"]="operations"; assert client.get("/api/audit-events").status_code==403
    current["role"]="owner"; assert client.get("/api/audit-events?tenant_id="+TEN_B).status_code==422


def test_legacy_activity_shape_maps_successful_audit_events(api):
    client, db, _=api
    started=build_event(user=USER_A,operation_id="op_activity",phase=AuditPhase.SUCCEEDED,
                        action="load.stage_changed",entity_type=AuditEntityType.LOAD,entity_id="L1",
                        previous={"stage":"Booked"},new={"stage":"Assigned"})
    db.audit_events.docs=[started]
    result=client.get("/api/activity?load_id=L1").json()
    assert len(result)==1 and set(result[0])=={"id","tenant_id","load_id","action","old_status","new_status","updated_by","timestamp","notes"}
    assert result[0]["action"]=="Stage Change" and result[0]["old_status"]=="Booked" and result[0]["new_status"]=="Assigned"


def test_incomplete_reconciliation_is_tenant_scoped_and_terminal_aware():
    db=FakeDB(); old=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
    started=build_event(user=USER_A,operation_id="op_open",phase=AuditPhase.STARTED,action="load.updated",entity_type=AuditEntityType.LOAD,entity_id="L1")
    started["occurred_at"]=old; started["integrity_hash"]=integrity_hash(started)
    complete=build_event(user=USER_A,operation_id="op_done",phase=AuditPhase.STARTED,action="load.updated",entity_type=AuditEntityType.LOAD,entity_id="L2")
    complete["occurred_at"]=old; complete["integrity_hash"]=integrity_hash(complete)
    terminal=build_event(user=USER_A,operation_id="op_done",phase=AuditPhase.SUCCEEDED,action="load.updated",entity_type=AuditEntityType.LOAD,entity_id="L2")
    foreign=build_event(user={**USER_A,"tenant_id":TEN_B},operation_id="op_foreign",phase=AuditPhase.STARTED,action="load.updated",entity_type=AuditEntityType.LOAD,entity_id="L3")
    foreign["occurred_at"]=old; foreign["integrity_hash"]=integrity_hash(foreign)
    db.audit_events.docs=[started,complete,terminal,foreign]
    result=asyncio.run(incomplete_operations(db.audit_events,TEN_A,300,10))
    assert [e["operation_id"] for e in result]==["op_open"]


def test_no_client_audit_create_update_or_delete_routes():
    methods={(route.path,method) for route in server.app.routes for method in getattr(route,"methods",set())}
    assert ("/api/audit-events","POST") not in methods
    assert not any(path.startswith("/api/audit-events") and method in {"PUT","PATCH","DELETE"} for path,method in methods)
