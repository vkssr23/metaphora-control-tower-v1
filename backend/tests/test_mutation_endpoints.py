"""Isolated FastAPI route tests for Security Patch 0B.1."""
import os
from types import SimpleNamespace

os.environ.update({"JWT_SECRET":"isolated-test-only-secret-value-over-32-characters", "MONGO_URL":"mongodb://127.0.0.1:1/no-network-test", "DB_NAME":"isolated", "CORS_ORIGINS":"http://localhost:3000", "APP_ENV":"test", "ALLOW_SEED_ENDPOINT":"false"})

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import server
VALID_TENANT = "ten_" + "a" * 32


class Cursor:
    def __init__(self, docs): self.docs=docs
    def sort(self, *args): return self
    async def to_list(self, length): return [dict(d) for d in self.docs[:length]]

class Collection:
    def __init__(self, docs=None):
        self.docs=list(docs or []); self.last_update=None; self.last_query=None; self.fail=False; self.matched_count_override=None
        for doc in self.docs: doc.setdefault("tenant_id", VALID_TENANT)
    async def find_one(self, query, *args):
        if self.fail: raise RuntimeError("mongodb://secret-host/private collection query")
        return next((dict(d) for d in self.docs if all(d.get(k, VALID_TENANT if k=="tenant_id" else None)==v for k,v in query.items())), None)
    def find(self, query=None, **kwargs): return Cursor([d for d in self.docs if all(d.get(k, VALID_TENANT if k=="tenant_id" else None)==v for k,v in (query or {}).items())])
    async def insert_one(self, doc):
        if self.fail: raise RuntimeError("mongodb://secret-host/private collection insert")
        self.docs.append(dict(doc)); return SimpleNamespace(inserted_id="fake")
    async def update_one(self, query, update, **kwargs):
        if self.fail: raise RuntimeError("mongodb://secret-host/private collection update")
        self.last_query=query; self.last_update=update
        matches=[doc for doc in self.docs if all(doc.get(k, VALID_TENANT if k=="tenant_id" else None)==v for k,v in query.items())]
        matched=len(matches) if self.matched_count_override is None else self.matched_count_override
        modified=0
        if matched:
            for doc in matches[:1]:
                doc.update(update.get("$set", {}))
                for key in update.get("$unset", {}): doc.pop(key, None)
                modified=1
        return SimpleNamespace(matched_count=matched, modified_count=modified)
    async def delete_one(self, query):
        if self.fail: raise RuntimeError("mongodb://secret-host/private collection delete")
        before=len(self.docs); self.docs=[d for d in self.docs if not all(d.get(k, VALID_TENANT if k=="tenant_id" else None)==v for k,v in query.items())]
        return SimpleNamespace(deleted_count=before-len(self.docs))

class FakeDB:
    def __init__(self):
        for name in ("users","tenants","loads","activity","audit_events","trucks","drivers","documents","invoices","assumptions"):
            setattr(self, name, Collection())

@pytest.fixture
def api(monkeypatch):
    fake=FakeDB(); monkeypatch.setattr(server, "db", fake); server.app.dependency_overrides.clear()
    def role(name):
        async def dependency(): return {"id":f"U-{name}", "name":"Authenticated Actor", "role":name, "tenant_id":VALID_TENANT}
        server.app.dependency_overrides[server.get_current_user]=dependency
    yield TestClient(server.app), fake, role
    server.app.dependency_overrides.clear()

def operational_routes():
    paths={"/api/routing/calc","/api/weather/check","/api/roads/check","/api/samsara/vehicle","/api/fuel/plan","/api/truckstops/plan","/api/alerts/generate","/api/loads/analyze","/api/ai/chat"}
    def expanded(routes):
        for route in routes:
            if isinstance(route, APIRoute): yield route
            elif hasattr(route, "original_router"): yield from expanded(route.original_router.routes)
    return [r for r in expanded(server.app.routes) if r.path in paths]

def test_no_operational_route_uses_raw_dict_and_unknown_fields_are_422(api):
    client, _, role=api; role("owner")
    payloads={
        "/api/routing/calc":{"pickup":"A","delivery":"B"}, "/api/weather/check":{"pickup":"A","delivery":"B"},
        "/api/roads/check":{"load_id":"L1"}, "/api/samsara/vehicle":{"truck_id":"T1"},
        "/api/fuel/plan":{"load_id":"L1"}, "/api/truckstops/plan":{"load_id":"L1"},
        "/api/alerts/generate":{"load_id":"L1","alert_type":"road"},
        "/api/loads/analyze":{"offered_rate":100,"loaded_miles":10}, "/api/ai/chat":{"message":"hello"},
    }
    assert len(operational_routes()) == len(payloads)
    for route in operational_routes():
        body=next(p for p in route.dependant.body_params)
        assert body.field_info.annotation is not dict
        assert client.post(route.path, json={**payloads[route.path], "unknown":"blocked"}).status_code == 422

def test_create_response_contracts_and_server_actors(api):
    client, db, role=api
    role("safety")
    truck=client.post("/api/trucks", json={"truck_number":"T1"}); assert truck.status_code==200 and truck.json()["profit_per_mile"]==0
    driver=client.post("/api/drivers", json={"name":"Driver"}); assert driver.status_code==200 and driver.json()["email"]==""
    explicit_blank=client.post("/api/drivers", json={"name":"Blank Email","email":""}); assert explicit_blank.status_code==200 and explicit_blank.json()["email"]==""
    assert db.drivers.docs[-1]["email"] == ""
    role("operations")
    load=client.post("/api/loads", json={"customer":"C","pickup_address":"A","delivery_address":"B","rate":0,"miles":100})
    assert load.status_code==200 and load.json()["rpm"]==0 and load.json()["dispatcher"]=="Authenticated Actor"
    doc=client.post("/api/documents", json={"load_id":load.json()["id"],"doc_type":"pod","filename":"pod.pdf","url":"mock://pod.pdf"})
    assert doc.status_code==200 and doc.json()["uploaded_by"]=="Authenticated Actor" and "uploaded_at" in doc.json()
    role("finance")
    invoice=client.post("/api/invoices", json={"load_id":load.json()["id"]})
    assert invoice.status_code==409 and not db.invoices.docs

@pytest.mark.parametrize("collection",["load_passports","execution_eligibility_cases","pickup_release_cases","execution_sessions","invoice_readiness_cases"])
def test_modern_lifecycle_evidence_rejects_legacy_invoice_create(api,collection):
    client,db,role=api;role("finance");db.loads.docs=[{"id":"L1","stage":"Assigned"}]
    setattr(db,collection,Collection([{"id":"X1","load_id":"L1"}]))
    assert client.post("/api/invoices",json={"load_id":"L1","amount":999}).status_code==409
    assert not db.invoices.docs

def test_delivered_without_readiness_is_not_assumed_legacy(api):
    client,db,role=api;role("finance");db.loads.docs=[{"id":"L1","stage":"Delivered"}]
    assert client.post("/api/invoices",json={"load_id":"L1","amount":999}).status_code==409

def test_historical_legacy_invoice_compatibility_and_malformed_modern_block(api):
    client,db,role=api;role("finance");db.loads.docs=[{"id":"L1"}]
    db.invoices.docs=[{"id":"OLD","load_id":"L1","amount":10,"status":"Not Ready","tenant_id":VALID_TENANT}]
    assert client.put("/api/invoices/OLD",json={"amount":11}).status_code==200
    db.invoices.docs=[{"id":"BAD","load_id":"L1","amount":10,"readiness_case_id":"R1","tenant_id":VALID_TENANT}]
    assert client.put("/api/invoices/BAD",json={"amount":12}).status_code==409
    assert db.invoices.docs[0]["amount"]==10

@pytest.mark.parametrize("field,value,old,expected", [("rate",500, {"rate":1000,"miles":100,"rpm":10},5), ("miles",200,{"rate":1000,"miles":100,"rpm":10},5), ("rate",0,{"rate":1000,"miles":100,"rpm":10},0), ("miles",0,{"rate":1000,"miles":100,"rpm":10},0)])
def test_load_updates_never_leave_stale_rpm(api, field, value, old, expected):
    client, db, role=api; role("operations"); db.loads.docs=[{"id":"L1", **old}]
    response=client.put("/api/loads/L1", json={field:value}); assert response.status_code==200
    assert db.loads.last_update["$set"]["rpm"] == expected
    assert set(db.loads.last_update["$set"]) == {field,"rpm","updated_at"}

def test_load_workflow_fields_and_actor_fields_are_not_general_updates(api):
    client, db, role=api; role("operations"); db.loads.docs=[{"id":"L1","rate":1,"miles":1}]
    for field in ("stage","bol_status","pod_status","invoice_status","payment_status","dispatcher","exception_origin_stage"):
        assert client.put("/api/loads/L1", json={field:"spoof"}).status_code==422

def test_alert_actor_and_role_policy(api):
    client, db, role=api; db.loads.docs=[{"id":"L1","stage":"Booked"}]
    role("operations")
    assert client.post("/api/alerts/generate", json={"load_id":"L1","alert_type":"road","dispatcher":"spoof"}).status_code==422
    response=client.post("/api/alerts/generate", json={"load_id":"L1","alert_type":"road","message":"test"})
    assert response.status_code==200 and db.audit_events.docs[-1]["actor_id"]=="U-operations"
    for denied in ("viewer","safety","finance"):
        role(denied); assert client.post("/api/alerts/generate", json={"load_id":"L1","alert_type":"road"}).status_code==403

def test_compliance_statuses_are_manual_safety_managed_enums(api):
    client, db, role=api; db.drivers.docs=[{"id":"D1","name":"Driver"}]
    role("operations")
    assert client.put("/api/drivers/D1", json={"mvr_status":"Clear"}).status_code==403
    role("safety")
    assert client.put("/api/drivers/D1", json={"mvr_status":"Clear","clearinghouse_status":"Pending","employment_verification":"Complete"}).status_code==200
    assert client.put("/api/drivers/D1", json={"mvr_status":"Externally Verified"}).status_code==422

def test_invoice_load_relationship_is_immutable(api):
    client, db, role=api; role("finance"); db.invoices.docs=[{"id":"I1","load_id":"L1","status":"Not Ready"}]
    assert client.put("/api/invoices/I1", json={"load_id":"L2"}).status_code==422
    response=client.put("/api/invoices/I1", json={"status":"Payment Pending"})
    assert response.status_code==200 and "load_id" not in db.invoices.last_update["$set"]

@pytest.mark.parametrize("resource,role_name,payload", [
    ("trucks","safety",{"status":"Available"}), ("drivers","safety",{"status":"Available"}),
    ("loads","operations",{"notes":"updated"}), ("invoices","finance",{"status":"Paid"}),
])
def test_updates_require_a_matched_record_after_pre_read(api, resource, role_name, payload):
    client, db, role=api; role(role_name); collection=getattr(db, resource); collection.docs=[{"id":"X1","rate":100,"miles":10}]
    assert client.put(f"/api/{resource}/X1", json=payload).status_code==200
    collection.matched_count_override=0
    assert client.put(f"/api/{resource}/X1", json=payload).status_code==404

@pytest.mark.parametrize("resource,role_name", [("trucks","safety"),("drivers","safety"),("loads","operations")])
def test_delete_success_and_missing_404(api, resource, role_name):
    client, db, role=api; role(role_name); collection=getattr(db, resource); collection.docs=[{"id":"X1"}]
    assert client.delete(f"/api/{resource}/X1").json()=={"ok":True}
    assert client.delete(f"/api/{resource}/missing").status_code==404

def test_database_errors_are_sanitized(api):
    client, db, role=api; role("safety"); db.trucks.fail=True
    response=TestClient(server.app, raise_server_exceptions=False).post("/api/trucks", json={"truck_number":"T1"})
    assert response.status_code==500 and response.json()=={"detail":"Database operation failed"}
    assert "mongodb" not in response.text.lower() and "collection" not in response.text.lower()

def test_document_creates_terminal_audit_without_legacy_activity(api):
    client, db, role=api; role("operations"); db.loads.docs=[{"id":"L1","tenant_id":VALID_TENANT}]
    response=client.post("/api/documents", json={"load_id":"L1","doc_type":"pod","filename":"pod.pdf","url":"mock://pod.pdf"})
    assert response.status_code==200 and db.documents.docs[-1]["filename"]=="pod.pdf"
    assert [e["phase"] for e in db.audit_events.docs]==["started","succeeded"] and db.activity.docs==[]

def test_corrected_frontend_payloads(api):
    client, db, role=api
    role("operations"); db.loads.docs=[{"id":"L1","stage":"Booked","rate":100,"miles":10}]; db.drivers.docs=[{"id":"D1","tenant_id":VALID_TENANT}]; db.trucks.docs=[{"id":"T1","tenant_id":VALID_TENANT}]
    assert client.put("/api/loads/L1", json={"driver_id":"D1","truck_id":"T1"}).status_code==200
    assert client.post("/api/loads/L1/stage", json={"stage":"Assigned","notes":"Assigned driver and truck"}).status_code==200
    assert client.post("/api/documents", json={"load_id":"L1","doc_type":"pod","filename":"pod_L1.pdf","url":"mock://pod_L1.pdf"}).status_code==200
    role("finance")
    assumptions={"fuel_price":3.8,"mpg":6.5,"driver_pay_solo_cpm":.6,"driver_pay_team_cpm":.9,"insurance_per_week":350,"rental_per_week":400,"factoring_fee_pct":3,"default_toll":60,"target_margin_pct":20,"min_rpm":1.85,"min_net_profit":400}
    assert client.put("/api/assumptions", json=assumptions).status_code==200
