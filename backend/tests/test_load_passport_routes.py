"""Isolated route coverage for Phase 1A.1 material-write ordering."""
import copy, os
from types import SimpleNamespace
os.environ.update({"JWT_SECRET":"isolated-test-only-secret-value-over-32-characters","MONGO_URL":"mongodb://127.0.0.1:1/no-network-test","DB_NAME":"isolated","CORS_ORIGINS":"http://localhost:3000","APP_ENV":"test","ALLOW_SEED_ENDPOINT":"false"})
import pytest
from fastapi.testclient import TestClient
import server

TENANT="ten_"+"a"*32
def nested(doc,key):
    value=doc
    for part in key.split("."):
        if not isinstance(value,dict): return None
        value=value.get(part)
    return value
def matches(doc,query):
    for key,wanted in query.items():
        actual=nested(doc,key)
        if isinstance(wanted,dict) and "$in" in wanted:
            if actual not in wanted["$in"]: return False
        elif actual!=wanted: return False
    return True
class Cursor:
    def __init__(self,docs): self.docs=docs
    def sort(self,*args): return self
    async def to_list(self,length): return [copy.deepcopy(d) for d in self.docs[:length]]
class Collection:
    def __init__(self,name,events,docs=None):
        self.name=name; self.events=events; self.docs=[copy.deepcopy(d) for d in (docs or [])]; self.matched_count_override=None; self.fail_insert=False; self.fail_update=False; self.update_calls=0; self.insert_calls=0
        for d in self.docs: d.setdefault("tenant_id",TENANT)
    async def find_one(self,query,*args):
        found=next((d for d in self.docs if matches(d,query)),None); return copy.deepcopy(found) if found else None
    def find(self,query=None,*args,**kwargs): return Cursor([d for d in self.docs if matches(d,query or {})])
    async def insert_one(self,doc):
        self.insert_calls+=1; self.events.append(f"{self.name}.insert")
        if self.fail_insert: raise RuntimeError("private database failure")
        self.docs.append(copy.deepcopy(doc)); return SimpleNamespace(inserted_id="fake")
    async def update_one(self,query,update,**kwargs):
        self.update_calls+=1; self.events.append(f"{self.name}.update")
        if self.fail_update: raise RuntimeError("private database failure")
        found=next((d for d in self.docs if matches(d,query)),None); count=(1 if found else 0) if self.matched_count_override is None else self.matched_count_override
        if count and found:
            found.update(copy.deepcopy(update.get("$set",{})))
            for key in update.get("$unset",{}): found.pop(key,None)
        return SimpleNamespace(matched_count=count,modified_count=count)
class FakeDB:
    def __init__(self):
        self.events=[]
        for name in ("users","tenants","loads","activity","audit_events","trucks","drivers","documents","invoices","assumptions","load_passports"):
            setattr(self,name,Collection(name,self.events))

def approved(status="pickup_authorized"):
    auth={"id":"pua_x","status":"active","issued_at":"now"} if status=="pickup_authorized" else None
    return {"id":"lps_x","tenant_id":TENANT,"load_id":"L1","version":4,"status":status,"approved_at":"now","approved_by":"U-owner","approved_version":4,"pickup_authorization":auth,"blocking_reasons":[],"checkpoints":[{"type":kind,"status":"pass","blocking":True} for kind in ("load_details","rate_confirmation","broker_identity","shipper_identity","profitability","driver_eligibility","truck_eligibility","trailer_eligibility","appointment_feasibility","pickup_instructions")],"load_snapshot":{"id":"L1","rate":1000,"miles":100},"assignment_snapshot":{"driver_id":"D1","truck_id":"T1"},"profitability_snapshot":{"estimated_net_profit":1},"required_checkpoint_types":[],"evidence_document_ids":[]}
@pytest.fixture
def api(monkeypatch):
    fake=FakeDB(); monkeypatch.setattr(server,"db",fake); server.app.dependency_overrides.clear()
    async def actor(): return {"id":"U-owner","name":"Owner","email":"owner@example.test","role":"owner","tenant_id":TENANT}
    server.app.dependency_overrides[server.get_current_user]=actor
    yield TestClient(server.app),fake
    server.app.dependency_overrides.clear()
def prepare(db,status="pickup_authorized"):
    db.loads.docs=[{"id":"L1","tenant_id":TENANT,"rate":1000,"miles":100,"stage":"Assigned","driver_id":"D1","truck_id":"T1","pickup_address":"A","delivery_address":"B"}]
    db.load_passports.docs=[approved(status)]

def test_material_load_race_blocks_canonical_write(api):
    client,db=api; prepare(db); before=copy.deepcopy(db.loads.docs[0]); db.load_passports.matched_count_override=0
    response=client.put("/api/loads/L1",json={"rate":1200})
    assert response.status_code==409 and db.loads.update_calls==0 and db.loads.docs[0]==before
    assert not any(e.get("phase")=="succeeded" and e.get("action")=="load_passport.material_change_invalidated" for e in db.audit_events.docs)
def test_successful_material_load_preinvalidates_then_writes(api):
    client,db=api; prepare(db); response=client.put("/api/loads/L1",json={"rate":1200})
    assert response.status_code==200 and db.events.index("load_passports.update") < db.events.index("loads.update")
    p=db.load_passports.docs[0]; assert p["status"]=="review_pending" and p["version"]==5 and p["pickup_authorization"]["status"]=="revoked" and "material_change_requires_reapproval" in p["blocking_reasons"]
    assert next(c for c in p["checkpoints"] if c["type"]=="profitability")["status"]=="pending" and db.loads.docs[0]["rate"]==1200
def test_load_failure_after_invalidation_never_restores_approval(api):
    client,db=api; prepare(db); db.loads.fail_update=True; response=client.put("/api/loads/L1",json={"rate":1200})
    assert response.status_code==500; p=db.load_passports.docs[0]; assert p["status"]=="review_pending" and p["pickup_authorization"]["status"]=="revoked" and p["approved_at"] is None
def test_rate_confirmation_race_prevents_insert(api):
    client,db=api; prepare(db); db.load_passports.matched_count_override=0
    response=client.post("/api/documents",json={"load_id":"L1","doc_type":"rate_con","filename":"rate.pdf","url":"mock://rate.pdf"})
    assert response.status_code==409 and db.documents.insert_calls==0
def test_rate_confirmation_preinvalidates_before_insert(api):
    client,db=api; prepare(db); response=client.post("/api/documents",json={"load_id":"L1","doc_type":"rate_con","filename":"rate.pdf","url":"mock://rate.pdf"})
    assert response.status_code==200 and db.events.index("load_passports.update") < db.events.index("documents.insert")
    p=db.load_passports.docs[0]; assert p["status"]=="review_pending" and p["pickup_authorization"]["status"]=="revoked"
def test_document_failure_after_invalidation_is_conservative(api):
    client,db=api; prepare(db); db.documents.fail_insert=True
    response=client.post("/api/documents",json={"load_id":"L1","doc_type":"rate_con","filename":"rate.pdf","url":"mock://rate.pdf"})
    assert response.status_code==500; p=db.load_passports.docs[0]; assert p["status"]=="review_pending" and p["pickup_authorization"]["status"]=="revoked"
def test_non_material_mutations_skip_invalidation(api):
    client,db=api; prepare(db); assert client.put("/api/loads/L1",json={"notes":"note"}).status_code==200; assert db.load_passports.update_calls==0
    assert client.post("/api/documents",json={"load_id":"L1","doc_type":"pod","filename":"pod.pdf","url":"mock://pod.pdf"}).status_code==200; assert db.load_passports.update_calls==0
def test_passport_creation_smoke_and_protected_fields(api):
    client,db=api; db.loads.docs=[{"id":"L1","tenant_id":TENANT,"rate":1000,"miles":100,"stage":"Assigned","driver_id":"D1","truck_id":"T1","pickup_address":"A","delivery_address":"B"}]; db.drivers.docs=[{"id":"D1","tenant_id":TENANT,"name":"Driver"}]; db.trucks.docs=[{"id":"T1","tenant_id":TENANT,"truck_number":"T1"}]; db.assumptions.docs=[{"id":"default","tenant_id":TENANT}]
    response=client.post("/api/loads/L1/passport",json={}); assert response.status_code==201 and "_id" not in response.json()
    assert client.post("/api/loads/L1/passport",json={"tenant_id":TENANT}).status_code==422
def test_approval_and_pickup_blockers_are_409(api):
    client,db=api; prepare(db,"review_pending"); p=db.load_passports.docs[0]; p["checkpoints"][0]["status"]="pending"; p["required_checkpoint_types"]=[p["checkpoints"][0]["type"]]
    assert client.post("/api/load-passports/lps_x/approve",json={}).status_code==409
    p["status"]="draft"; assert client.post("/api/load-passports/lps_x/authorize-pickup",json={}).status_code==409
def test_cross_tenant_get_and_version_race(api):
    client,db=api; prepare(db,"draft"); db.load_passports.docs[0]["tenant_id"]="ten_"+"b"*32; assert client.get("/api/load-passports/lps_x").status_code==404
    db.load_passports.docs[0]["tenant_id"]=TENANT; db.load_passports.matched_count_override=0; assert client.put("/api/load-passports/lps_x",json={"trailer_identifier":"T"}).status_code==409
def test_audit_start_failure_blocks_passport_mutation(api):
    client,db=api; prepare(db,"draft"); db.audit_events.fail_insert=True
    assert client.put("/api/load-passports/lps_x",json={"trailer_identifier":"T"}).status_code==503 and db.load_passports.update_calls==0
