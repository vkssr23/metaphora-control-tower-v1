"""Offline Phase 2F deterministic policy and projection lifecycle tests."""
import asyncio
from datetime import datetime, timezone
from app.domain.action_center import build_candidates, REASON_POLICY, POLICY_VERSION
from app.infrastructure.action_center_projection import ProjectionConflict, _resolve_source_cleared, acknowledge, reconcile_projection
from app.application.action_center_service import IncompleteSourceSnapshot, load_source_snapshot, refresh_tenant, SOURCE_COLLECTIONS
from app.permissions import can_acknowledge_action
from test_rate_confirmation_routes import Collection, api, h, USERS, TA as ROUTE_TA, TB

TA="tenant-a"
NOW=datetime(2026,1,1,tzinfo=timezone.utc)

def run(value):return asyncio.run(value)
def snapshot(**overrides):
    base={"loads":[],"documents":[],"load_passports":[],"party_verification_cases":[],"execution_eligibility_cases":[],"pickup_release_cases":[],"execution_sessions":[],"execution_exceptions":[],"invoice_readiness_cases":[],"accessorials":[],"reconciliation_items":[],"production_integrity_findings":[]}
    base.update(overrides);return base

def test_controlled_policy_and_stable_identity():
    case={"id":"P1","load_id":"L1","status":"blocked","blocking_reasons":["rate_confirmation_stale"]}
    first=build_candidates(snapshot(pickup_release_cases=[case]))[0]
    second=build_candidates(snapshot(pickup_release_cases=[dict(case)]))[0]
    assert first.active_identity==second.active_identity and first.reason_code in REASON_POLICY
    assert first.owner_role=="operations" and first.severity=="high" and first.document()["projection_version"]==POLICY_VERSION

def test_source_detectors_group_duplicates_and_preserve_supporting_impacts():
    case={"id":"P1","load_id":"L1","status":"blocked","blocking_reasons":["party_verification_required","rate_confirmation_stale"]}
    items=build_candidates(snapshot(pickup_release_cases=[case,dict(case)]))
    assert len(items)==1 and items[0].supporting_reasons==("party_verification_required","rate_confirmation_stale")

def test_execution_resolved_exception_and_ready_sources_do_not_emit():
    values=build_candidates(snapshot(
        party_verification_cases=[{"id":"PV","load_id":"L","status":"cleared"}],
        execution_eligibility_cases=[{"id":"EE","load_id":"L","status":"eligible"}],
        execution_exceptions=[{"id":"EX","load_id":"L","status":"resolved"}],
        invoice_readiness_cases=[{"id":"IR","load_id":"L","status":"ready"}]))
    assert values==[]

def test_delivery_pod_and_finance_policy():
    load={"id":"L","stage":"Delivered"};case={"id":"IR","load_id":"L","status":"blocked","blockers":["pod_present"]}
    reasons={x.reason_code for x in build_candidates(snapshot(loads=[load],invoice_readiness_cases=[case]))}
    assert reasons=={"pod_missing_after_delivery","invoice_readiness_blocked"}
    reasons={x.reason_code for x in build_candidates(snapshot(loads=[load],documents=[{"id":"D","load_id":"L","doc_type":"pod"}],invoice_readiness_cases=[{"id":"IR","load_id":"L","status":"ready"}]))}
    assert not reasons

def test_party_wording_never_confirms_fraud():
    item=build_candidates(snapshot(party_verification_cases=[{"id":"PV","load_id":"L","status":"blocked"}]))[0]
    assert "not a fraud confirmation" in item.summary.lower()

def test_projection_create_dedup_ack_preservation_clear_and_recurrence():
    col=Collection("action_items",[]);candidate=build_candidates(snapshot(party_verification_cases=[{"id":"PV","load_id":"L","status":"blocked"}]))
    run(reconcile_projection(col,TA,candidate,NOW));run(reconcile_projection(col,TA,candidate,NOW));assert len(col.docs)==1
    item=col.docs[0];ack,outcome=run(acknowledge(col,TA,item["id"],"U1",item["version"],NOW));assert outcome=="acknowledged"
    run(reconcile_projection(col,TA,candidate,NOW));assert col.docs[0]["status"]=="acknowledged" and col.docs[0]["acknowledged_by"]=="U1"
    run(reconcile_projection(col,TA,[],NOW));assert col.docs[0]["status"]=="resolved"
    run(reconcile_projection(col,TA,candidate,NOW));assert len(col.docs)==2 and sum(x["status"]=="open" for x in col.docs)==1

def test_ack_version_tenant_and_resolved_guards():
    col=Collection("action_items",[]);candidate=build_candidates(snapshot(reconciliation_items=[{"id":"R","operation_id":"O","entity_id":"E","status":"open"}]))
    run(reconcile_projection(col,TA,candidate,NOW));item=col.docs[0]
    assert run(acknowledge(col,"other",item["id"],"U",1,NOW))[1]=="not_found"
    assert run(acknowledge(col,TA,item["id"],"U",99,NOW))[1]=="conflict"
    run(reconcile_projection(col,TA,[],NOW));assert run(acknowledge(col,TA,item["id"],"U",item["version"]+1,NOW))[1]=="resolved"

def test_integrity_and_reconciliation_are_admin_owned():
    items=build_candidates(snapshot(reconciliation_items=[{"id":"R","operation_id":"O","entity_id":"E","status":"open"}],production_integrity_findings=[{"id":"F","code":"BROKEN","severity":"critical","status":"open"}]))
    assert {x.owner_role for x in items}=={"admin"} and {x.category for x in items}=={"reconciliation","platform_integrity"}

def test_source_snapshot_completeness_below_boundary_at_boundary_and_over_cap():
    col=Collection("source",[],[{"id":str(i),"tenant_id":TA} for i in range(4)])
    assert run(load_source_snapshot(col,TA,cap=5)).complete
    col.docs.append({"id":"4","tenant_id":TA});at=run(load_source_snapshot(col,TA,cap=5));assert at.complete and len(at.records)==5
    col.docs.append({"id":"5","tenant_id":TA});over=run(load_source_snapshot(col,TA,cap=5));assert not over.complete and len(over.records)==5

class Sources:
    def __init__(self):
        self.events=[]
        for name in (*SOURCE_COLLECTIONS,"action_items"):setattr(self,name,Collection(name,self.events))

def test_incomplete_or_failed_source_preserves_open_and_acknowledged_projection(monkeypatch):
    import app.application.action_center_service as service
    for status in ("open","acknowledged"):
        db=Sources();db.action_items.docs=[{"id":"A","tenant_id":TA,"active_identity":"old","status":status,"version":1}]
        db.loads.docs=[{"id":str(i),"tenant_id":TA} for i in range(3)]
        monkeypatch.setattr(service,"SOURCE_RECORD_CAP",2)
        try:run(refresh_tenant(db,TA));assert False
        except IncompleteSourceSnapshot:pass
        assert db.action_items.docs[0]["status"]==status and not db.action_items.update_calls
    db=Sources();db.action_items.docs=[{"id":"A","tenant_id":TA,"active_identity":"old","status":"open","version":1}]
    def fail(*args,**kwargs):raise RuntimeError("query failure")
    db.loads.find=fail
    try:run(refresh_tenant(db,TA));assert False
    except RuntimeError:pass
    assert db.action_items.docs[0]["status"]=="open" and not db.action_items.update_calls

class RacingCollection(Collection):
    def __init__(self,always_conflict=False):super().__init__("action_items",[]);self.always_conflict=always_conflict;self.attempts=0
    async def update_one(self,query,update,**kwargs):
        self.attempts+=1
        if self.attempts==1 and not self.always_conflict:
            self.docs[0].update({"status":"acknowledged","acknowledged_at":"ack-time","acknowledged_by":"U","version":2})
            from types import SimpleNamespace
            return SimpleNamespace(matched_count=0,modified_count=0)
        if self.always_conflict:
            from types import SimpleNamespace
            return SimpleNamespace(matched_count=0,modified_count=0)
        result=await super().update_one(query,update,**kwargs)
        if result.matched_count:self.docs[0]["version"]=self.docs[0].get("version",1)+1
        return result

def test_source_clear_retries_ack_race_and_preserves_ack_history():
    col=RacingCollection();col.docs=[{"id":"A","tenant_id":TA,"active_identity":"I","status":"open","version":1}]
    resolved=run(_resolve_source_cleared(col,TA,dict(col.docs[0]),"resolved-time"))
    assert resolved["status"]=="resolved" and resolved["acknowledged_at"]=="ack-time" and resolved["acknowledged_by"]=="U" and col.attempts==2
    assert run(_resolve_source_cleared(col,TA,resolved,"later"))["status"]=="resolved"
    assert run(_resolve_source_cleared(col,TB,{**resolved,"status":"open"},"later")) is None

def test_source_clear_repeated_conflict_is_bounded_failure():
    col=RacingCollection(True);col.docs=[{"id":"A","tenant_id":TA,"active_identity":"I","status":"open","version":1}]
    import pytest
    with pytest.raises(ProjectionConflict):run(_resolve_source_cleared(col,TA,dict(col.docs[0]),"now",max_attempts=3))
    assert col.attempts==3

def test_three_recurrences_are_monotonic_unique_and_do_not_inherit_ack():
    col=Collection("action_items",[]);candidate=build_candidates(snapshot(party_verification_cases=[{"id":"PV","load_id":"L","status":"blocked"}]))
    ids=[]
    for generation in (1,2,3):
        run(reconcile_projection(col,TA,candidate,datetime(2026,1,generation,tzinfo=timezone.utc)))
        active=next(x for x in col.docs if x["status"]=="open");ids.append(active["id"]);assert active["incident_generation"]==generation and active["acknowledged_by"] is None
        run(reconcile_projection(col,TA,candidate,datetime(2026,1,generation,tzinfo=timezone.utc)));assert len([x for x in col.docs if x["status"]=="open"])==1
        run(reconcile_projection(col,TA,[],datetime(2026,1,generation,tzinfo=timezone.utc)))
    assert len(set(ids))==3 and [x["incident_generation"] for x in col.docs]==[1,2,3] and all(x["status"]=="resolved" for x in col.docs)

def test_category_owner_permission_matrix_and_invalid_mapping_fail_closed():
    users={role:{"role":role} for role in ("operations","safety","finance","viewer","owner","admin")}
    expected={"operations":{"operations","owner","admin"},"safety":{"safety","owner","admin"},"finance":{"finance","owner","admin"},"admin":{"owner","admin"}}
    categories={"operations":"execution","safety":"fraud_risk","finance":"finance","admin":"platform_integrity"}
    for owner,allowed in expected.items():
        action={"owner_role":owner,"category":categories[owner]}
        assert {role for role,user in users.items() if can_acknowledge_action(user,action)}==allowed
    assert not can_acknowledge_action(users["operations"],{"owner_role":"operations","category":"finance"})

def _prepare_action_api(db,owner):
    for name in (*SOURCE_COLLECTIONS,"action_items"):
        if not hasattr(db,name):setattr(db,name,Collection(name,db.events))
    if owner=="operations":db.pickup_release_cases.docs=[{"id":"P","tenant_id":ROUTE_TA,"load_id":"L1","status":"blocked"}]
    elif owner=="safety":db.party_verification_cases.docs=[{"id":"PV","tenant_id":ROUTE_TA,"load_id":"L1","status":"blocked"}]
    elif owner=="finance":db.invoice_readiness_cases.docs=[{"id":"IR","tenant_id":ROUTE_TA,"load_id":"L1","status":"blocked"}]
    else:db.production_integrity_findings.docs=[{"id":"F","tenant_id":ROUTE_TA,"code":"BROKEN","severity":"critical","status":"open"}]

def test_acknowledgement_route_permission_matrix_and_tenant_nonleakage(api):
    client,db=api;USERS.update({"safety":{"id":"U-safe","role":"safety","tenant_id":ROUTE_TA},"admin":{"id":"U-admin","role":"admin","tenant_id":ROUTE_TA}});db.users.docs.extend([USERS["safety"],USERS["admin"]])
    _prepare_action_api(db,"operations")
    allowed={"operations":{"ops","owner","admin"},"safety":{"safety","owner","admin"},"finance":{"finance","owner","admin"},"admin":{"owner","admin"}}
    for owner in allowed:
        for name in SOURCE_COLLECTIONS:getattr(db,name).docs=[]
        db.action_items.docs=[];_prepare_action_api(db,owner)
        item=client.get("/api/action-center",headers=h("owner")).json()["items"][0]
        for role in ("ops","safety","finance","viewer","owner","admin"):
            response=client.post(f"/api/action-center/{item['id']}/acknowledge",json={"version":item["version"]},headers=h(role))
            assert response.status_code==(200 if role in allowed[owner] else 403)
            if response.status_code==200:db.action_items.docs[0].update({"status":"open","acknowledged_at":None,"acknowledged_by":None,"version":item["version"]})
    assert client.post("/api/action-center/not-in-this-tenant/acknowledge",json={"version":1},headers=h("viewer")).status_code==404

def test_multi_detector_cascade_keeps_distinct_owned_work():
    items=build_candidates(snapshot(load_passports=[{"id":"PP","load_id":"L","pickup_authorization":{"status":"revoked"}}],pickup_release_cases=[{"id":"PR","load_id":"L","status":"blocked","blocking_reasons":["party_verification_required","execution_not_eligible"]}],party_verification_cases=[{"id":"PV","load_id":"L","status":"review_pending"}],execution_eligibility_cases=[{"id":"EE","load_id":"L","status":"blocked"}]))
    assert {x.reason_code for x in items}=={"pickup_authorization_revoked","party_verification_required","execution_not_eligible"}
    pickup=next(x for x in items if x.reason_code=="pickup_authorization_revoked")
    assert pickup.supporting_reasons==("execution_not_eligible","party_verification_required")
