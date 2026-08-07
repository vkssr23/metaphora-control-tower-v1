"""Real FastAPI Phase 1F tests using fake collections and DB-backed users."""
import copy,pytest
from fastapi import Header,HTTPException
from fastapi.testclient import TestClient
from test_rate_confirmation_routes import FakeDB,Collection,LOAD,USERS,TA,TB,h,server

def session(tenant=TA,status="active",version=1):
 return {"id":"exs_a" if tenant==TA else "exs_b","tenant_id":tenant,"load_id":"L1" if tenant==TA else "LB","passport_id":"P1","pickup_release_case_id":"PR1","execution_eligibility_case_id":"E1","version":version,"status":status,"execution_state":"pickup_confirmed","created_at":"2026-01-01T00:00:00Z","created_by":"U-ops","started_at":"2026-01-01T00:00:00Z","started_by":"U-ops","updated_at":"2026-01-01T00:00:00Z","updated_by":"U-ops","current_checkpoint":"pickup_confirmed","current_stop_index":0,"total_stops":2,"stops":[{"stop_index":0,"stop_type":"pickup","planned_location":{},"planned_arrival":None,"planned_departure":None,"actual_arrival":"2026-01-01T00:00:00Z","actual_departure":None,"status":"arrived","detention_state":"none","reference":""},{"stop_index":1,"stop_type":"delivery","planned_location":{},"planned_arrival":"2026-01-02T10:00:00Z","planned_departure":None,"actual_arrival":None,"actual_departure":None,"status":"pending","detention_state":"none","reference":""}],"planned_snapshot":{"driver_id":"D1","truck_id":"T1","delivery":{"address":"2 Oak","appointment":"2026-01-02T10:00:00Z"}},"planning_history":[],"actual_snapshot":{},"eta_snapshot":{"status":"unknown","eta_source":"unknown"},"detention_snapshot":{"state":"none"},"route_progress_snapshot":{"route_status":"unknown","source":"manual"},"latest_event_at":"2026-01-01T00:00:00Z","latest_event_id":None,"open_exception_count":0,"critical_exception_count":0,"execution_health":"healthy","custody_state":"pickup_confirmed","source_state":"manual","last_material_change_at":"2026-01-01T00:00:00Z"}

@pytest.fixture
def api(monkeypatch):
 db=FakeDB()
 for name in ("pickup_release_cases","execution_eligibility_cases","party_verification_cases","execution_sessions","execution_events","execution_exceptions","tenants","drivers","trucks"):
  setattr(db,name,Collection(name,db.events))
 load={**copy.deepcopy(LOAD),"stage":"Loaded","driver_id":"D1","truck_id":"T1","deadhead_miles":10,"notes":""}
 db.loads.docs=[load,{**load,"id":"LB","tenant_id":TB}]
 db.drivers.docs=[{"id":"D1","tenant_id":TA},{"id":"D2","tenant_id":TA}];db.trucks.docs=[{"id":"T1","tenant_id":TA},{"id":"T2","tenant_id":TA}]
 db.load_passports.docs=[{"id":"P1","tenant_id":TA,"load_id":"L1","version":4,"status":"pickup_authorized","pickup_authorization":{"status":"consumed"}}]
 db.pickup_release_cases.docs=[{"id":"PR1","tenant_id":TA,"load_id":"L1","passport_id":"P1","execution_eligibility_case_id":"E1","version":3,"status":"pickup_confirmed","custody_state":"pickup_confirmed","pickup_confirmed_at":"2026-01-01T00:00:00Z","assignment_snapshot":{"driver_id":"D1","truck_id":"T1","trailer_identifier":"TRL1"}}]
 db.documents.docs=[{"id":"POD1","tenant_id":TA,"load_id":"L1","doc_type":"pod"},{"id":"FOREIGN","tenant_id":TB,"load_id":"LB","doc_type":"pod"}]
 monkeypatch.setattr(server,"db",db);server.app.dependency_overrides.clear()
 async def actor(x_test_user:str=Header("ops")):
  record=await db.users.find_one({"id":USERS.get(x_test_user,USERS["ops"])["id"]})
  if not record:raise HTTPException(401,"User unavailable")
  record.pop("_id",None);return record
 server.app.dependency_overrides[server.get_current_user]=actor
 yield TestClient(server.app),db
 server.app.dependency_overrides.clear()

def start(c,body=None,user="ops"):return c.post("/api/loads/L1/execution-session/start",json={} if body is None else body,headers=h(user))
def seed(db,status="active",version=1):db.execution_sessions.docs=[session(status=status,version=version)];return db.execution_sessions.docs[0]

def test_start_confirmed_is_server_controlled_audit_first(api):
 c,db=api;r=start(c);assert r.status_code==201,r.text;x=r.json();assert x["id"].startswith("exs_") and x["tenant_id"]==TA and x["version"]==1 and x["status"]=="active" and "_id" not in x
 assert db.events.index("audit_events.insert")<db.events.index("execution_sessions.insert")
def test_start_fail_closed_prerequisites_and_protected_fields(api):
 c,db=api
 for field,value,code in (("status","released",409),("custody_state","authorized",409)):
  old=db.pickup_release_cases.docs[0][field];db.pickup_release_cases.docs[0][field]=value;assert start(c).status_code==code;db.pickup_release_cases.docs[0][field]=old
 db.loads.docs[0]["driver_id"]="D2";assert start(c).status_code==409;db.loads.docs[0]["driver_id"]="D1"
 db.loads.docs[0]["stage"]="Assigned";assert start(c).status_code==409;db.loads.docs[0]["stage"]="Loaded"
 assert start(c,{"tenant_id":TA}).status_code==422
def test_start_missing_foreign_and_audit_failure(api):
 c,db=api;db.pickup_release_cases.docs=[];assert start(c).status_code==409
 db.pickup_release_cases.docs=[{"id":"B","tenant_id":TB,"load_id":"L1","status":"pickup_confirmed"}];assert start(c).status_code==409
 db.pickup_release_cases.docs=[{"id":"PR1","tenant_id":TA,"load_id":"L1","passport_id":"P1","version":1,"status":"pickup_confirmed","custody_state":"pickup_confirmed","assignment_snapshot":{"driver_id":"D1","truck_id":"T1"}}];db.audit_events.fail_insert=True;assert start(c).status_code==503 and not db.execution_sessions.docs
def test_tenant_isolation_lists_reads_mutations_and_no_delete(api):
 c,db=api;db.execution_sessions.docs=[session(),session(TB)]
 assert [x["id"] for x in c.get("/api/execution-sessions",headers=h("ops")).json()]==["exs_a"]
 for path,method,body in (("/api/execution-sessions/exs_a","get",None),("/api/execution-sessions/exs_a/progress","post",{"version":1}),("/api/execution-sessions/exs_a/complete","post",{"version":1})):
  r=getattr(c,method)(path,headers=h("foreign"),**({"json":body} if body else {}));assert r.status_code==404
 assert c.get("/api/execution-sessions",headers=h("tenantless")).status_code==403
 assert c.delete("/api/execution-sessions/exs_a",headers=h("owner")).status_code==405
def test_progress_sources_bounds_version_terminal_and_event(api):
 c,db=api;seed(db);body={"version":1,"source":"manual","current_location_text":"Columbus, OH","remaining_miles_estimate":200,"driver_reported_eta":"2026-01-02T10:20:00Z"};r=c.post("/api/execution-sessions/exs_a/progress",json=body,headers=h("ops"));assert r.status_code==200,r.text
 assert r.json()["version"]==2 and db.execution_events.docs[-1]["type"]=="progress_reported" and "not_gps_verified" in str(r.json())
 for source in ("system","future_driver_app","future_telematics","future_eld","future_broker_tracking","future_shipper_tracking","future_weather","future_maps","bogus"):
  assert c.post("/api/execution-sessions/exs_a/progress",json={"version":2,"source":source},headers=h("ops")).status_code==422
 assert c.post("/api/execution-sessions/exs_a/progress",json={"version":2,"remaining_miles_estimate":-1},headers=h("ops")).status_code==422
 for value in ("NaN","Infinity"):
  assert c.post("/api/execution-sessions/exs_a/progress",json={"version":2,"remaining_miles_estimate":value},headers=h("ops")).status_code==422
 assert c.post("/api/execution-sessions/exs_a/progress",json={"version":1},headers=h("ops")).status_code==409
 db.execution_sessions.docs[0]["status"]="completed";assert c.post("/api/execution-sessions/exs_a/progress",json={"version":2},headers=h("ops")).status_code==409
def test_eta_thresholds_and_internal_source(api):
 c,db=api
 for eta,status in (("","unknown"),("2026-01-02T10:15:00Z","on_time"),("2026-01-02T10:16:00Z","at_risk"),("2026-01-02T10:31:00Z","late")):
  seed(db);r=c.post("/api/execution-sessions/exs_a/eta/evaluate",json={"version":1,"manual_eta":eta},headers=h("ops"));assert r.status_code==200 and r.json()["eta_snapshot"]["status"]==status and r.json()["eta_snapshot"]["eta_source"] in {"manual","unknown"}
 assert not any(x in str(db.execution_events.docs).lower() for x in ("traffic verified","weather verified","maps verified"))
def test_stop_order_departure_and_events(api):
 c,db=api;seed(db);assert c.post("/api/execution-sessions/exs_a/stops/1/depart",json={"version":1},headers=h("ops")).status_code==409
 r=c.post("/api/execution-sessions/exs_a/stops/0/depart",json={"version":1},headers=h("ops"));assert r.status_code==200
 r=c.post("/api/execution-sessions/exs_a/stops/1/arrive",json={"version":2},headers=h("ops"));assert r.status_code==200 and r.json()["stops"][1]["status"]=="arrived"
 assert [x["type"] for x in db.execution_events.docs]==["stop_departed","stop_arrived"]
 assert c.post("/api/execution-sessions/exs_a/stops/1/arrive",json={"version":3},headers=h("ops")).status_code==409
def test_detention_server_duration_evidence_and_claims(api):
 c,db=api;seed(db);assert c.post("/api/execution-sessions/exs_a/detention/start",json={"version":1,"stop_index":0,"started_at":"2026-01-01T10:00:00Z"},headers=h("ops")).status_code==422;r=c.post("/api/execution-sessions/exs_a/detention/start",json={"version":1,"stop_index":0,"supporting_document_ids":["POD1"]},headers=h("ops"));assert r.status_code==200
 assert c.post("/api/execution-sessions/exs_a/detention/start",json={"version":2,"stop_index":0},headers=h("ops")).status_code==409
 assert c.post("/api/execution-sessions/exs_a/detention/end",json={"version":2,"ended_at":"2026-01-01T09:00:00Z"},headers=h("ops")).status_code==422
 r=c.post("/api/execution-sessions/exs_a/detention/end",json={"version":2},headers=h("ops"));assert r.status_code==200 and r.json()["detention_snapshot"]["duration_minutes"]>=0
 assert c.post("/api/execution-sessions/exs_a/detention/start",json={"version":3,"stop_index":0,"duration_minutes":4},headers=h("ops")).status_code==422
 assert "automatically_verified" not in str(r.json())
def test_exception_lifecycle_roles_versions_and_owner_tenant(api):
 c,db=api;seed(db);payload={"version":1,"type":"driver_reported_issue","category":"driver","severity":"warning","title":"Driver update"};r=c.post("/api/execution-sessions/exs_a/exceptions",json=payload,headers=h("ops"));assert r.status_code==201,r.text;e=r.json();assert e["status"]=="open" and "_id" not in e
 assert c.put(f"/api/execution-exceptions/{e['id']}/acknowledge",json={"version":1},headers=h("ops")).status_code==200
 assert c.put(f"/api/execution-exceptions/{e['id']}/escalate",json={"version":2},headers=h("ops")).status_code==200
 assert c.put(f"/api/execution-exceptions/{e['id']}/assign",json={"version":3,"owner_user_id":"U-foreign"},headers=h("ops")).status_code==404
 assert c.put(f"/api/execution-exceptions/{e['id']}/waive",json={"version":3,"reason":""},headers=h("ops")).status_code==403
 assert c.put(f"/api/execution-exceptions/{e['id']}/resolve",json={"version":3,"reason":"reviewed"},headers=h("ops")).status_code==200
def test_delivery_arrival_confirmation_pod_and_completion(api):
 c,db=api;s=seed(db);s["stops"][0].update({"status":"departed","actual_departure":"2026-01-01T01:00:00Z"});db.loads.docs[0]["stage"]="Arrived Delivery"
 arrived=c.post("/api/execution-sessions/exs_a/delivery-arrive",json={"version":1},headers=h("ops"));assert arrived.status_code==200,arrived.text;db.documents.docs=[]
 confirm=c.post("/api/execution-sessions/exs_a/delivery-confirm",json={"version":3,"source":"manual"},headers=h("ops"));assert confirm.status_code==200,confirm.text;assert db.loads.docs[0]["stage"]=="Delivered"
 assert c.post("/api/execution-sessions/exs_a/complete",json={"version":4},headers=h("ops")).status_code==409;assert any(x["type"]=="pod_missing" for x in db.execution_exceptions.docs)
 db.documents.docs=[{"id":"POD1","tenant_id":TA,"load_id":"L1","doc_type":"pod"}];done=c.post("/api/execution-sessions/exs_a/complete",json={"version":4},headers=h("ops"));assert done.status_code==200,done.text
 assert c.post("/api/execution-sessions/exs_a/complete",json={"version":5},headers=h("ops")).status_code==409
def test_plan_amendment_preserves_history_role_and_race(api):
 c,db=api;old=copy.deepcopy(seed(db)["planned_snapshot"]);assert c.post("/api/execution-sessions/exs_a/amend-plan",json={"version":1,"delivery_appt":"2026-01-03T10:00:00Z","reason":"Customer approved"},headers=h("ops")).status_code==403
 r=c.post("/api/execution-sessions/exs_a/amend-plan",json={"version":1,"delivery_appt":"2026-01-03T10:00:00Z","reason":"Customer approved"},headers=h("owner"));assert r.status_code==200 and r.json()["planning_history"][0]["snapshot"]==old
 assert c.post("/api/execution-sessions/exs_a/amend-plan",json={"version":1,"reason":"race"},headers=h("owner")).status_code==409
def test_material_update_order_history_exception_and_nonmaterial(api):
 c,db=api;old=copy.deepcopy(seed(db)["planned_snapshot"]);mark=len(db.events);r=c.put("/api/loads/L1",json={"delivery_appt":"2026-01-03T12:00:00Z"},headers=h("ops"));assert r.status_code==200,r.text
 segment=db.events[mark:];assert segment.index("audit_events.insert")<segment.index("execution_sessions.update")<segment.index("execution_events.insert")<segment.index("execution_exceptions.insert")<segment.index("loads.update")
 assert db.execution_sessions.docs[0]["planned_snapshot"]==old and db.execution_sessions.docs[0]["execution_health"]=="at_risk" and db.execution_exceptions.docs[0]["type"]=="execution_plan_material_change"
 db.execution_events.docs=[];db.execution_exceptions.docs=[];db.events=[];db.execution_sessions.docs=[session()];assert c.put("/api/loads/L1",json={"notes":"ordinary note"},headers=h("ops")).status_code==200
 assert not db.execution_events.docs and not db.execution_exceptions.docs and db.execution_sessions.docs[0]["execution_health"]=="healthy"
def test_material_race_and_evidence_failure_block_load(api):
 c,db=api;seed(db);db.execution_sessions.matched_count_override=0;before=db.loads.docs[0]["commodity"];assert c.put("/api/loads/L1",json={"commodity":"Steel"},headers=h("ops")).status_code==409 and db.loads.docs[0]["commodity"]==before
 db.execution_sessions.matched_count_override=None;db.execution_sessions.docs=[session()];db.execution_events.fail_insert=True;assert c.put("/api/loads/L1",json={"equipment_type":"Reefer"},headers=h("ops")).status_code==503 and db.loads.docs[0]["equipment_type"]!="Reefer"
def test_canonical_failure_preserves_material_history(api):
 c,db=api;seed(db);db.loads.fail_update=True;r=c.put("/api/loads/L1",json={"miles":522},headers=h("ops"));assert r.status_code==500 and db.execution_events.docs and db.execution_exceptions.docs and db.execution_sessions.docs[0]["status"]=="exception"
def test_reads_bounded_sorted_and_external_claims(api):
 c,db=api;seed(db);db.execution_events.docs=[{"id":"e1","tenant_id":TA,"execution_session_id":"exs_a","occurred_at":"2026-01-01"}];db.execution_exceptions.docs=[]
 assert c.get("/api/execution-sessions?limit=201",headers=h("ops")).status_code==422
 assert c.get("/api/execution-sessions/exs_a/events?limit=501",headers=h("ops")).status_code==422
 assert c.get("/api/execution-sessions/exs_a/events",headers=h("ops")).json()[0]["id"]=="e1"
 text=str(c.get("/api/execution-sessions/exs_a",headers=h("ops")).json()).lower()
 for claim in ("gps verified","telematics verified","eld verified","traffic verified","weather verified","geofence verified"):assert claim not in text

def test_authoritative_timestamp_fields_rejected(api):
 c,db=api;seed(db)
 calls=[("/api/execution-sessions/exs_a/stops/0/depart",{"version":1,"occurred_at":"2000-01-01T00:00:00Z"}),("/api/execution-sessions/exs_a/detention/start",{"version":1,"stop_index":0,"started_at":"2000-01-01T00:00:00Z"}),("/api/execution-sessions/exs_a/detention/end",{"version":1,"ended_at":"2000-01-01T00:00:00Z"}),("/api/execution-sessions/exs_a/delivery-arrive",{"version":1,"occurred_at":"2000-01-01T00:00:00Z"})]
 for path,body in calls:assert c.post(path,json=body,headers=h("ops")).status_code==422
 db.execution_sessions.docs=[session(status="delivery_arrived")];db.loads.docs[0]["stage"]="Arrived Delivery"
 assert c.post("/api/execution-sessions/exs_a/delivery-confirm",json={"version":1,"delivered_at":"2000-01-01T00:00:00Z"},headers=h("ops")).status_code==422

def test_exception_owner_role_is_database_authoritative(api):
 c,db=api;seed(db);payload={"version":1,"type":"delivery_eta_at_risk","category":"timing","severity":"high","title":"ETA review","owner_user_id":"U-ops"}
 r=c.post("/api/execution-sessions/exs_a/exceptions",json=payload,headers=h("ops"));assert r.status_code==201,r.text;assert r.json()["owner_role"]=="operations"
 assert c.post("/api/execution-sessions/exs_a/exceptions",json={**payload,"version":2,"owner_role":"owner"},headers=h("ops")).status_code==422
 driver={"version":2,"type":"driver_reported_issue","category":"driver","severity":"warning","title":"Driver review","owner_user_id":"U-ops"}
 assert c.post("/api/execution-sessions/exs_a/exceptions",json=driver,headers=h("ops")).status_code==409

def test_current_release_blocks_historical_bypass_ambiguity_and_duplicate(api):
 c,db=api;old=db.pickup_release_cases.docs[0];old.update({"updated_at":"2026-01-01","version":1})
 for status in ("review_pending","revoked","exception"):
  db.pickup_release_cases.docs=[copy.deepcopy(old),{**copy.deepcopy(old),"id":"NEW","status":status,"updated_at":"2026-01-02","version":2}];assert start(c).status_code==409
 db.pickup_release_cases.docs=[copy.deepcopy(old),{**copy.deepcopy(old),"id":"TWIN","updated_at":"2026-01-01","version":1}];assert start(c).status_code==409
 db.pickup_release_cases.docs=[copy.deepcopy(old),{**copy.deepcopy(old),"id":"FOREIGN-NEW","tenant_id":TB,"status":"revoked","updated_at":"2026-01-03"}];assert start(c).status_code==201
 db.execution_sessions.docs=[session()];assert start(c).status_code==409

def delivery_ready(db):
 s=session(status="delivery_arrived");s["execution_state"]="arrived_delivery";s["current_stop_index"]=1;s["stops"][0]["status"]="departed";s["stops"][1]["status"]="arrived";db.execution_sessions.docs=[s];db.loads.docs[0]["stage"]="Arrived Delivery";return s

def test_delivery_confirmation_safe_order_and_server_time(api):
 c,db=api;delivery_ready(db);mark=len(db.events);r=c.post("/api/execution-sessions/exs_a/delivery-confirm",json={"version":1},headers=h("ops"));assert r.status_code==200,r.text
 segment=db.events[mark:];assert segment.index("audit_events.insert")<segment.index("execution_sessions.update")<segment.index("execution_events.insert")<segment.index("loads.update")
 assert r.json()["actual_snapshot"]["delivery_confirmed_at"]!="2000-01-01T00:00:00Z" and db.loads.docs[0]["stage"]=="Delivered"
 before=len([x for x in db.execution_events.docs if x["type"]=="delivery_confirmed"]);assert c.post("/api/execution-sessions/exs_a/delivery-confirm",json={"version":2},headers=h("ops")).status_code==409;assert len([x for x in db.execution_events.docs if x["type"]=="delivery_confirmed"])==before

def test_delivery_session_race_and_audit_failure_do_not_touch_load(api):
 c,db=api;delivery_ready(db);db.execution_sessions.matched_count_override=0;assert c.post("/api/execution-sessions/exs_a/delivery-confirm",json={"version":1},headers=h("ops")).status_code==409 and db.loads.docs[0]["stage"]=="Arrived Delivery" and not db.execution_events.docs
 db.execution_sessions.matched_count_override=None;delivery_ready(db);db.audit_events.fail_insert=True;assert c.post("/api/execution-sessions/exs_a/delivery-confirm",json={"version":1},headers=h("ops")).status_code==503 and db.loads.docs[0]["stage"]=="Arrived Delivery" and not db.execution_events.docs

def test_delivery_event_failure_preserves_reconciliation_and_not_load(api):
 c,db=api;delivery_ready(db);db.execution_events.fail_insert=True;r=c.post("/api/execution-sessions/exs_a/delivery-confirm",json={"version":1},headers=h("ops"));assert r.status_code==503 and db.loads.docs[0]["stage"]=="Arrived Delivery" and db.execution_sessions.docs[0]["status"]=="exception"

def test_delivery_load_race_and_failure_preserve_event_and_reconcile(api):
 c,db=api;delivery_ready(db);db.loads.matched_count_override=0;r=c.post("/api/execution-sessions/exs_a/delivery-confirm",json={"version":1},headers=h("ops"));assert r.status_code==409 and db.loads.docs[0]["stage"]=="Arrived Delivery" and db.execution_events.docs[-1]["type"]=="delivery_confirmed" and db.execution_sessions.docs[0]["status"]=="exception"
 db.loads.matched_count_override=None;delivery_ready(db);db.execution_events.docs=[];db.loads.fail_update=True;r=c.post("/api/execution-sessions/exs_a/delivery-confirm",json={"version":1},headers=h("ops"));assert r.status_code==503 and db.execution_events.docs and db.execution_sessions.docs[0]["status"]=="exception"

def test_eta_delay_route_server_evaluated_at_and_protected(api):
 c,db=api;seed(db);assert c.post("/api/execution-sessions/exs_a/eta/evaluate",json={"version":1,"manual_eta":"2026-01-02T10:31:00Z","evaluated_at":"2000-01-01T00:00:00Z"},headers=h("ops")).status_code==422
 r=c.post("/api/execution-sessions/exs_a/eta/evaluate",json={"version":1,"manual_eta":"2026-01-02T10:31:00Z"},headers=h("ops"));assert r.status_code==200 and r.json()["eta_snapshot"]["status"]=="late" and r.json()["delay_snapshot"]["reason_code"]=="eta_variance"
