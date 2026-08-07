"""Authoritative isolated FastAPI coverage for Security Patch 0C/0C.1.

This replaces the historic network-based ``test_auth_signup.py`` for tenant
signup behavior. No real database, provider, seed endpoint, or network is used.
"""
import os
import re
import asyncio
from dataclasses import replace
from types import SimpleNamespace

os.environ.update({"JWT_SECRET":"isolated-test-only-secret-value-over-32-characters", "MONGO_URL":"mongodb://127.0.0.1:1/no-network-test", "DB_NAME":"isolated", "CORS_ORIGINS":"http://localhost:3000", "APP_ENV":"test", "ALLOW_SEED_ENDPOINT":"false"})

import pytest
import jwt
from fastapi import HTTPException
from fastapi.testclient import TestClient
import server
from app.schemas import AiChatRequest
from app.security import authenticated_user_dependency
from app.tenant import require_tenant_id, tenant_document, tenant_filter

TEN_A = "ten_" + "a" * 32
TEN_B = "ten_" + "b" * 32


def matches(doc, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(matches(doc, option) for option in expected): return False
        elif isinstance(expected, dict) and "$exists" in expected:
            if (key in doc) != expected["$exists"]: return False
        elif isinstance(expected, re.Pattern):
            if not isinstance(doc.get(key), str) or not expected.fullmatch(doc[key]): return False
        elif key == "tenant_id" and {"ten_A":TEN_A,"ten_B":TEN_B}.get(doc.get(key),doc.get(key)) != expected: return False
        elif key != "tenant_id" and doc.get(key) != expected: return False
    return True


class Cursor:
    def __init__(self, docs): self.docs = docs
    def sort(self, key, direction=None):
        fields = key if isinstance(key, list) else [(key, direction)]
        for field, order in reversed(fields): self.docs.sort(key=lambda d: d.get(field, ""), reverse=order < 0)
        return self
    async def to_list(self, length): return [dict(d) for d in self.docs[:length]]


class Collection:
    def __init__(self, docs=None):
        self.docs=list(docs or []); self.queries=[]; self.inserts=[]; self.deletes=[]; self.fail_insert=False; self.matched_count_override=None
    async def find_one(self, query, *args):
        self.queries.append(dict(query)); return next((dict(d) for d in self.docs if matches(d, query)), None)
    def find(self, query=None, *args):
        self.queries.append(dict(query or {})); return Cursor([d for d in self.docs if matches(d, query or {})])
    async def insert_one(self, doc):
        if self.fail_insert: raise RuntimeError("private database detail")
        self.inserts.append(dict(doc)); self.docs.append(dict(doc)); return SimpleNamespace(inserted_id="fake")
    async def insert_many(self, docs):
        for doc in docs: await self.insert_one(doc)
    async def update_one(self, query, update, **kwargs):
        self.queries.append(dict(query)); found=[d for d in self.docs if matches(d, query)]
        count=len(found) if self.matched_count_override is None else self.matched_count_override
        if count and found:
            found[0].update(update.get("$setOnInsert", {})); found[0].update(update.get("$set", {}))
        elif kwargs.get("upsert"):
            doc={**query, **update.get("$setOnInsert", {}), **update.get("$set", {})}; self.docs.append(doc); count=1
        return SimpleNamespace(matched_count=count)
    async def delete_one(self, query):
        self.deletes.append(dict(query)); before=len(self.docs); self.docs=[d for d in self.docs if not matches(d, query)]
        return SimpleNamespace(deleted_count=before-len(self.docs))
    async def delete_many(self, query):
        self.deletes.append(dict(query)); before=len(self.docs); self.docs=[d for d in self.docs if not matches(d, query)]
        return SimpleNamespace(deleted_count=before-len(self.docs))
    async def count_documents(self, query): return len([d for d in self.docs if matches(d, query)])


class FakeDB:
    def __init__(self):
        for name in ("users","tenants","trucks","drivers","loads","documents","invoices","activity","audit_events","assumptions"):
            setattr(self, name, Collection())


@pytest.fixture
def api(monkeypatch):
    fake=FakeDB(); monkeypatch.setattr(server, "db", fake); server.app.dependency_overrides.clear()
    def login(tenant="ten_A", role="owner"):
        membership={"ten_A":TEN_A,"ten_B":TEN_B}.get(tenant,tenant)
        async def current(): return {"id":f"U_{tenant}", "email":f"{tenant}@test.invalid", "name":"Actor", "role":role, "tenant_id":membership} if tenant else {"id":"legacy", "role":role, "name":"Legacy"}
        server.app.dependency_overrides[server.get_current_user]=current
    yield TestClient(server.app), fake, login
    server.app.dependency_overrides.clear()


def test_helpers_fail_closed_and_override_spoof():
    source={"id":"L1","tenant_id":TEN_B}
    assert tenant_filter({"tenant_id":TEN_A}, source)["tenant_id"]==TEN_A
    assert tenant_document({"tenant_id":TEN_A}, source)["tenant_id"]==TEN_A and source["tenant_id"]==TEN_B
    with pytest.raises(HTTPException) as exc: require_tenant_id({"role":"owner"})
    assert exc.value.status_code==403


@pytest.mark.parametrize("membership", [None,"","   ","org_"+"a"*32,"ten_"+"A"*32,"ten_"+"a"*31,"ten_"+"a"*33,"ten_"+"g"*32])
def test_database_membership_is_canonical_and_fails_closed(membership):
    user={"role":"owner"}
    if membership is not None: user["tenant_id"]=membership
    with pytest.raises(HTTPException) as exc: require_tenant_id(user)
    assert exc.value.status_code==403 and exc.value.detail=="Tenant membership is required"


def test_valid_database_membership_is_accepted():
    assert require_tenant_id({"tenant_id":TEN_A})==TEN_A


def test_spoofed_jwt_tenant_cannot_rescue_malformed_database_membership(api):
    client, db, _=api
    db.users.docs=[{"id":"U1","email":"user@example.com","name":"User","role":"owner","tenant_id":" malformed "}]
    database_user=authenticated_user_dependency(db,server.settings.jwt_secret)
    server.app.dependency_overrides[server.get_current_user]=database_user
    token=jwt.encode({"id":"U1","tenant_id":TEN_A,"role":"owner"},server.settings.jwt_secret,algorithm="HS256")
    response=client.get("/api/loads",headers={"Authorization":f"Bearer {token}"})
    assert response.status_code==403 and response.json()=={"detail":"Tenant membership is required"}


def test_tenantless_user_and_query_spoof(api):
    client, db, login=api; db.loads.docs=[{"id":"A","tenant_id":"ten_A"},{"id":"B","tenant_id":"ten_B"}]
    login(None); assert client.get("/api/loads").status_code==403
    login("ten_A","viewer"); response=client.get("/api/loads?tenant_id=ten_B")
    assert [d["id"] for d in response.json()]==["A"]


@pytest.mark.parametrize("role", ["owner","admin","viewer"])
def test_lists_details_dashboard_compliance_are_tenant_scoped(api, role):
    client, db, login=api; login("ten_A",role)
    for name in ("loads","trucks","drivers","documents","invoices","activity"):
        getattr(db,name).docs=[{"id":f"{name}A","tenant_id":"ten_A","name":"A","truck_number":"A","timestamp":"2"},{"id":f"{name}B","tenant_id":"ten_B","name":"B","truck_number":"B","timestamp":"3"}]
    assert [x["id"] for x in client.get("/api/loads").json()]==["loadsA"]
    assert client.get("/api/loads/loadsB").status_code==404
    assert [x["id"] for x in client.get("/api/trucks").json()]==["trucksA"]
    assert [x["id"] for x in client.get("/api/drivers").json()]==["driversA"]
    assert [x["id"] for x in client.get("/api/documents").json()]==["documentsA"]
    assert [x["id"] for x in client.get("/api/invoices").json()]==["invoicesA"]
    assert [x["id"] for x in client.get("/api/activity").json()]==["activityA"]
    assert client.get("/api/dashboard/stats").json()["active_loads"]==1
    assert client.get("/api/compliance").json()["summary"]["total"]==2


def test_crud_predicates_and_relationships_are_tenant_scoped(api):
    client, db, login=api
    db.drivers.docs=[{"id":"DA","tenant_id":"ten_A","name":"A"},{"id":"DB","tenant_id":"ten_B","name":"B"}]
    db.trucks.docs=[{"id":"TA","tenant_id":"ten_A","truck_number":"A"},{"id":"TB","tenant_id":"ten_B","truck_number":"B"}]
    login("ten_A","safety")
    assert client.post("/api/trucks",json={"truck_number":"NEW","assigned_driver_id":"DA"}).json()["tenant_id"]==TEN_A
    assert client.post("/api/trucks",json={"truck_number":"X","assigned_driver_id":"DB"}).status_code==404
    assert client.put("/api/trucks/TA",json={"assigned_driver_id":"DA"}).status_code==200
    assert client.put("/api/trucks/TB",json={"status":"Available"}).status_code==404
    assert client.delete("/api/trucks/TB").status_code==404 and any(d["id"]=="TB" for d in db.trucks.docs)
    assert db.trucks.queries[-1]["tenant_id"]==TEN_A
    assert client.post("/api/drivers",json={"name":"New","assigned_truck_id":"TB"}).status_code==404
    login("ten_A","operations")
    db.loads.docs=[{"id":"LA","tenant_id":"ten_A","stage":"Booked","rate":1,"miles":1},{"id":"LB","tenant_id":"ten_B","stage":"Booked","rate":1,"miles":1}]
    assert client.put("/api/loads/LA",json={"driver_id":"DA","truck_id":"TA"}).status_code==200
    assert client.put("/api/loads/LA",json={"driver_id":"DB"}).status_code==404
    assert client.post("/api/documents",json={"load_id":"LB","doc_type":"pod","filename":"p.pdf","url":"mock://p.pdf"}).status_code==404
    login("ten_A","finance")
    assert client.post("/api/invoices",json={"load_id":"LB"}).status_code==404


@pytest.mark.parametrize("path", ["/api/roads/check","/api/fuel/plan","/api/truckstops/plan"])
def test_load_helpers_reject_foreign_ids(api, path):
    client, db, login=api; login("ten_A","operations"); db.loads.docs=[{"id":"LB","tenant_id":"ten_B"}]
    assert client.post(path,json={"load_id":"LB"}).status_code==404


def test_samsara_contract_is_tenant_scoped_and_simulated(api):
    client, db, login=api; login("ten_A","operations")
    db.trucks.docs=[{"id":"TA","tenant_id":"ten_A","samsara_id":"stored-A"},{"id":"TB","tenant_id":"ten_B","samsara_id":"stored-B"},{"id":"TN","tenant_id":"ten_A"}]
    response=client.post("/api/samsara/vehicle",json={"truck_id":"TA"})
    assert response.status_code==200 and response.json()["simulated"] is True and response.json()["vehicle_id"]=="stored-A"
    assert client.post("/api/samsara/vehicle",json={"truck_id":"TB"}).status_code==404
    assert client.post("/api/samsara/vehicle",json={"truck_id":"missing"}).status_code==404
    assert client.post("/api/samsara/vehicle",json={"truck_id":"VEH123"}).status_code==422
    assert client.post("/api/samsara/vehicle",json={"vehicle_id":"VEH999"}).status_code==404
    assert client.post("/api/samsara/vehicle",json={"vehicle_id":"stored-B"}).status_code==404
    assert client.post("/api/samsara/vehicle",json={"truck_id":"TA","tenant_id":"ten_B"}).status_code==422
    assert client.post("/api/samsara/vehicle",json={"truck_id":"TN"}).json()["vehicle_id"]=="simulated:TN"


def test_assumptions_are_isolated_and_upsert_scoped(api):
    client, db, login=api; db.assumptions.docs=[{"id":"default","tenant_id":"ten_B","fuel_price":9}]
    login("ten_A","viewer"); result=client.get("/api/assumptions").json()
    assert result["tenant_id"]==TEN_A and any(d["tenant_id"]=="ten_B" and d["fuel_price"]==9 for d in db.assumptions.docs)
    login("ten_A","finance"); assert client.put("/api/assumptions",json={"fuel_price":4}).status_code==200
    assert db.assumptions.queries[-1]=={"id":"default","tenant_id":TEN_A}


def test_transition_cross_tenant_writes_no_activity(api):
    client, db, login=api; login("ten_A","operations"); db.loads.docs=[{"id":"LB","tenant_id":"ten_B","stage":"Booked"}]
    assert client.post("/api/loads/LB/stage",json={"stage":"Assigned"}).status_code==404
    assert db.activity.docs==[]


def test_foreign_alert_creates_no_activity(api):
    client, db, login=api; login("ten_A","operations"); db.loads.docs=[{"id":"LB","tenant_id":"ten_B","stage":"Booked"}]
    assert client.post("/api/alerts/generate",json={"load_id":"LB","alert_type":"road"}).status_code==404
    assert db.activity.docs==[]


def test_ai_context_queries_are_tenant_scoped_without_provider_call(api):
    _, db, _=api; user={"id":"UA","name":"A","role":"owner","tenant_id":TEN_A}
    for name in ("loads","trucks","drivers","invoices"):
        getattr(db,name).docs=[{"id":"A","tenant_id":"ten_A"},{"id":"B","tenant_id":"ten_B"}]
    response=asyncio.run(server.ai_chat(AiChatRequest(message="hello"),user))
    assert response.media_type=="text/plain"
    for name in ("loads","trucks","drivers","invoices"):
        assert getattr(db,name).queries[-1]=={"tenant_id":TEN_A}


def test_signup_route_success_isolated_and_compatible(api):
    client, db, _=api
    payload={"name":"New User","email":"new@example.com","password":"long-enough-password"}
    first=client.post("/api/auth/signup",json=payload); second=client.post("/api/auth/signup",json={**payload,"email":"two@example.com"})
    assert first.status_code==second.status_code==200
    assert set(first.json())=={"token","user"} and "tenant_id" in first.json()["user"]
    users=db.users.docs; assert users[0]["role"]=="viewer" and re.fullmatch(r"ten_[0-9a-f]{32}",users[0]["tenant_id"])
    assert first.json()["user"]["tenant_id"]==users[0]["tenant_id"]==db.tenants.docs[0]["id"]
    assert second.json()["user"]["tenant_id"]==users[1]["tenant_id"]==db.tenants.docs[1]["id"]
    assert users[0]["tenant_id"]!=users[1]["tenant_id"]
    assert {d["tenant_id"] for d in db.assumptions.docs}=={users[0]["tenant_id"],users[1]["tenant_id"]}


@pytest.mark.parametrize("role", ["owner","admin","dispatcher","finance","safety"])
def test_signup_rejects_privileged_roles_and_tenant_field(api, role):
    client, db, _=api; payload={"name":"X","email":f"{role}@example.com","password":"long-enough-password","role":role}
    assert client.post("/api/auth/signup",json=payload).status_code==403
    assert client.post("/api/auth/signup",json={**payload,"role":"viewer","tenant_id":"ten_B"}).status_code==422
    assert db.tenants.docs==[]


@pytest.mark.parametrize("field", ["organization_id","workspace_id","account_id","tenant"])
def test_signup_rejects_tenant_alias_fields(api, field):
    client, db, _=api
    payload={"name":"X","email":f"{field}@example.com","password":"long-enough-password",field:"foreign"}
    assert client.post("/api/auth/signup",json=payload).status_code==422
    assert db.tenants.docs==[]


def test_duplicate_signup_precedes_tenant_creation(api):
    client, db, _=api; db.users.docs=[{"id":"U","email":"dup@example.com"}]
    assert client.post("/api/auth/signup",json={"name":"X","email":"DUP@example.com","password":"long-enough-password"}).status_code==400
    assert db.tenants.docs==[]


def test_returned_membership_cannot_override_database_authority(api):
    client, db, login=api
    db.loads.docs=[{"id":"A","tenant_id":"ten_A"},{"id":"B","tenant_id":"ten_B"}]
    returned_membership="ten_B"; login("ten_A","viewer")
    assert returned_membership=="ten_B" and [d["id"] for d in client.get("/api/loads?tenant_id="+returned_membership).json()]==["A"]


def test_signup_failures_cleanup_exact_new_tenant_only(api, caplog):
    client, db, _=api; db.tenants.docs=[{"id":"ten_existing","name":"Existing"}]; db.users.fail_insert=True
    response=TestClient(server.app,raise_server_exceptions=False).post("/api/auth/signup",json={"name":"X","email":"x@example.com","password":"long-enough-password"})
    assert response.status_code==500 and response.json()=={"detail":"Database operation failed"}
    assert db.tenants.docs==[{"id":"ten_existing","name":"Existing"}]
    assert len(db.tenants.deletes)==1 and re.fullmatch(r"ten_[0-9a-f]{32}",db.tenants.deletes[0]["id"])
    assert "private database detail" not in caplog.text


def test_tenant_insert_failure_creates_no_user(api):
    client, db, _=api; db.tenants.fail_insert=True
    assert TestClient(server.app,raise_server_exceptions=False).post("/api/auth/signup",json={"name":"X","email":"x@example.com","password":"long-enough-password"}).status_code==500
    assert db.users.docs==[]


def test_assumption_signup_failure_is_best_effort_and_later_repaired(api):
    client, db, login=api; db.assumptions.fail_insert=True
    response=client.post("/api/auth/signup",json={"name":"X","email":"x@example.com","password":"long-enough-password"})
    assert response.status_code==200
    tenant=db.users.docs[0]["tenant_id"]; db.assumptions.fail_insert=False; login(tenant,"viewer")
    assert client.get("/api/assumptions").json()["tenant_id"]==tenant


def test_seed_force_is_tenant_scoped_with_fake_collections(api, monkeypatch):
    client, db, login=api; login("ten_A","owner")
    for name in ("loads","trucks","drivers","documents","invoices","activity"):
        getattr(db,name).docs=[{"id":f"{name}B","tenant_id":"ten_B"}]
    monkeypatch.setattr(server,"settings",replace(server.settings,allow_seed_endpoint=True,app_env="test"))
    response=client.post("/api/seed?force=true")
    assert response.status_code==200
    for name in ("loads","trucks","drivers","documents","invoices","activity"):
        collection=getattr(db,name); assert any(d.get("tenant_id")=="ten_B" for d in collection.docs)
        assert all(q=={"tenant_id":TEN_A} for q in collection.deletes)
        assert all(d.get("tenant_id")==TEN_A for d in collection.inserts)
    assert db.users.deletes==[] and db.tenants.deletes==[]


def test_tenantless_owner_cannot_seed(api, monkeypatch):
    client, _, login=api; login(None,"owner"); monkeypatch.setattr(server,"settings",replace(server.settings,allow_seed_endpoint=True,app_env="test"))
    assert client.post("/api/seed?force=true").status_code==403
