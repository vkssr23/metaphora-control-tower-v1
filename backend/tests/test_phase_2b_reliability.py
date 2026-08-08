"""Offline Phase 2B operation, outbox, reconciliation, UoW, and invoice tests."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from functools import wraps
from types import SimpleNamespace

import pytest

from app.domain.outbox_policy import MAX_ATTEMPTS, retry_delay
from app.infrastructure.operations import OperationConflict, create_or_replay, idempotency_identity, transition
from app.infrastructure.outbox import claim_next, enqueue, mark_delivered, mark_failed
from app.infrastructure.outbox_worker import process_one
from app.infrastructure.reconciliation import ensure_reconciliation
from app.infrastructure.unit_of_work import TransactionRequirement, select_unit_of_work
from app.production_integrity import scan_integrity
from test_invoice_readiness_routes import api, h, ready
from test_rate_confirmation_routes import Collection, TA, TB, USERS


def collection(name="records"):
    return Collection(name, [])


def sync_test(function):
    @wraps(function)
    def run(): return asyncio.run(function())
    return run


@sync_test
async def test_operation_identity_is_tenant_command_target_scoped_and_key_bounded():
    key = "same-key"
    a = idempotency_identity(TA, "invoice.create", "case", "A", key)
    assert a != idempotency_identity(TB, "invoice.create", "case", "A", key)
    assert a != idempotency_identity(TA, "invoice.cancel", "case", "A", key)
    assert a != idempotency_identity(TA, "invoice.create", "case", "B", key)
    with pytest.raises(ValueError): idempotency_identity(TA, "invoice.create", "case", "A", "bad key")


@sync_test
async def test_operation_replay_active_conflict_and_reconciliation_closed():
    col = collection("operations")
    kwargs = dict(tenant_id=TA, operation_type="invoice.create", target_type="invoice_readiness_case",
                  target_id="R", idempotency_key="K", request_id="REQ", actor=USERS["owner"])
    op, replay = await create_or_replay(col, **kwargs)
    assert not replay and op["status"] == "started" and len(op["steps"]) == 6
    with pytest.raises(OperationConflict) as active: await create_or_replay(col, **kwargs)
    assert active.value.code == "operation_in_progress"
    op = await transition(col, op, step="readiness_claimed")
    op = await transition(col, op, status="reconciliation_required", step="package_created", step_status="failed", failure_code="package_failure")
    with pytest.raises(OperationConflict) as blocked: await create_or_replay(col, **kwargs)
    assert blocked.value.code == "reconciliation_required"


@sync_test
async def test_operation_success_replays_safe_reference_without_new_record():
    col = collection("operations")
    kwargs = dict(tenant_id=TA, operation_type="invoice.create", target_type="invoice_readiness_case",
                  target_id="R", idempotency_key="K2", request_id="REQ", actor=USERS["owner"])
    op, _ = await create_or_replay(col, **kwargs)
    for step in ("readiness_claimed","package_created","invoice_created"):
        op = await transition(col, op, step=step)
    op = await transition(col, op, status="committing", step="readiness_finalized")
    op = await transition(col, op, status="succeeded", step="outbox_recorded", result_reference={"invoice_id": "I"})
    replay, existing = await create_or_replay(col, **kwargs)
    assert existing and replay["result_reference"] == {"invoice_id": "I"} and len(col.docs) == 1


@sync_test
async def test_operation_version_guard_rejects_stale_transition():
    col = collection("operations")
    op, _ = await create_or_replay(col, tenant_id=TA, operation_type="invoice.create",
        target_type="invoice_readiness_case", target_id="R", idempotency_key=None,
        request_id="REQ", actor=USERS["owner"])
    op=await transition(col, op, step="readiness_claimed");stale=copy.deepcopy(op);stale["version"]-=1
    with pytest.raises(OperationConflict): await transition(col, stale, step="package_created")


@sync_test
async def test_reconciliation_creation_is_deduplicated_and_tenant_scoped():
    col = collection("reconciliation_items")
    kwargs = dict(operation_id="OP", domain="invoice", entity_type="invoice", entity_id="I",
                  reason_code="invoice_failure", summary="Safe controlled summary")
    first = await ensure_reconciliation(col, tenant_id=TA, **kwargs)
    again = await ensure_reconciliation(col, tenant_id=TA, **kwargs)
    other = await ensure_reconciliation(col, tenant_id=TB, **kwargs)
    assert first["id"] == again["id"] and other["id"] != first["id"] and len(col.docs) == 2


@sync_test
async def test_outbox_payload_control_and_enqueue_deduplication():
    col = collection("outbox_events")
    kwargs = dict(tenant_id=TA, operation_id="OP", event_type="invoice.ready_for_submission",
                  aggregate_type="invoice", aggregate_id="I", payload={"invoice_id": "I"})
    first = await enqueue(col, **kwargs); second = await enqueue(col, **kwargs)
    assert first["id"] == second["id"] and len(col.docs) == 1 and first["payload_version"] == 1
    with pytest.raises(ValueError):
        await enqueue(col, tenant_id=TA, operation_id="OP2", event_type="invoice.ready_for_submission",
                      aggregate_type="invoice", aggregate_id="I2", payload={"password": "secret"})


@sync_test
async def test_only_one_worker_claims_and_stale_worker_cannot_deliver():
    col = collection("outbox_events"); now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    await enqueue(col, tenant_id=TA, operation_id="OP", event_type="invoice.ready_for_submission",
                  aggregate_type="invoice", aggregate_id="I", payload={"invoice_id": "I"}, stamp=now)
    first = await claim_next(col, tenant_id=TA, worker_id="A", now=now, lease_seconds=10)
    assert first and await claim_next(col, tenant_id=TA, worker_id="B", now=now) is None
    reclaimed = await claim_next(col, tenant_id=TA, worker_id="B", now=now + timedelta(seconds=11))
    assert reclaimed["claim_owner"] == "B" and reclaimed["claim_token"] != first["claim_token"]
    assert not await mark_delivered(col, first, now=now + timedelta(seconds=12))
    assert await mark_delivered(col, reclaimed, now=now + timedelta(seconds=12))


@sync_test
async def test_retry_backoff_exhaustion_and_unknown_handler_dead_letter():
    assert retry_delay(1).total_seconds() == 30 and retry_delay(3).total_seconds() == 120
    col = collection("outbox_events"); now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    event = await enqueue(col, tenant_id=TA, operation_id="OP", event_type="invoice.ready_for_submission",
                          aggregate_type="invoice", aggregate_id="I", payload={"invoice_id": "I"}, stamp=now)
    claimed = await claim_next(col, tenant_id=TA, worker_id="A", now=now)
    ok, state = await mark_failed(col, claimed, error_code="temporary", safe_summary="Temporary failure", now=now)
    assert ok and state == "retryable" and col.docs[0]["next_attempt_at"] == (now + timedelta(seconds=30)).isoformat()
    col.docs[0].update({"status":"pending", "next_attempt_at":now.isoformat(), "attempt_count":MAX_ATTEMPTS-1})
    claimed = await claim_next(col, tenant_id=TA, worker_id="A", now=now)
    ok, state = await mark_failed(col, claimed, error_code="temporary", safe_summary="Safe", now=now)
    assert ok and state == "dead_letter"
    col2=collection("outbox_events"); await enqueue(col2, tenant_id=TA, operation_id="OP2", event_type="invoice.ready_for_submission", aggregate_type="invoice", aggregate_id="I2", payload={"invoice_id":"I2"}, stamp=now)
    assert (await process_one(col2,tenant_id=TA,worker_id="W",handlers={},now=now))["result"] == "dead_letter"


def test_unit_of_work_is_explicit_and_required_never_falls_back():
    saga = select_unit_of_work(TransactionRequirement.PREFERRED)
    assert not saga.capability.atomic_multi_document_writes and saga.capability.transaction_capability == "unverified"
    with pytest.raises(RuntimeError, match="transaction_required_but_unverified"):
        select_unit_of_work(TransactionRequirement.REQUIRED)


@sync_test
async def test_supplied_transaction_adapter_commits_success_and_aborts_failure():
    class Transaction:
        async def __aenter__(self): self.session.pending=[]; return self
        async def __aexit__(self, kind, value, trace):
            if kind is None: self.session.committed.extend(self.session.pending)
            self.session.pending=[]
        def __init__(self, session): self.session=session
    class Session:
        def __init__(self): self.pending=[]; self.committed=[]
        def start_transaction(self): return Transaction(self)
    session=Session(); uow=select_unit_of_work(verified_session=session)
    async def success(active): active.pending.extend(["business", "outbox"]); return "ok"
    assert await uow.execute(success)=="ok" and session.committed==["business","outbox"]
    async def failure(active): active.pending.extend(["business", "outbox"]); raise RuntimeError("simulated")
    with pytest.raises(RuntimeError,match="simulated"): await uow.execute(failure)
    assert session.committed==["business","outbox"] and session.pending==[]


def test_integrity_reports_phase2b_missing_links_dead_letter_and_missing_event():
    operation={"id":"OP","tenant_id":TA,"operation_type":"invoice.create","status":"succeeded","version":1}
    report=scan_integrity({"tenants":[{"id":TA}],"operations":[operation],"outbox_events":[],"reconciliation_items":[]},generated_at="2026-01-01T00:00:00+00:00")
    assert "SUCCEEDED_OPERATION_OUTBOX_MISSING" in {x["code"] for x in report["findings"]}
    event={"id":"E","tenant_id":TA,"operation_id":"MISSING","status":"dead_letter","version":1}
    report=scan_integrity({"tenants":[{"id":TA}],"operations":[],"outbox_events":[event],"reconciliation_items":[]},generated_at="2026-01-01T00:00:00+00:00")
    assert {"OUTBOX_OPERATION_MISSING","OUTBOX_DEAD_LETTERED"} <= {x["code"] for x in report["findings"]}


def test_invoice_success_operation_outbox_and_idempotent_replay(api):
    client,db=api; case=ready(client,True); headers={**h("owner"),"Idempotency-Key":"invoice-R-1"}
    first=client.post(f"/api/invoice-readiness-cases/{case['id']}/invoice",json={"version":3},headers=headers)
    replay=client.post(f"/api/invoice-readiness-cases/{case['id']}/invoice",json={"version":3},headers=headers)
    assert first.status_code==replay.status_code==201 and first.json()["id"]==replay.json()["id"]
    assert len(db.operations.docs)==len(db.outbox_events.docs)==len(db.invoices.docs)==len(db.invoice_packages.docs)==1
    assert db.operations.docs[0]["status"]=="succeeded" and db.operations.docs[0]["audit_operation_id"]==db.operations.docs[0]["id"]
    assert db.outbox_events.docs[0]["event_type"]=="invoice.ready_for_submission"


def test_invoice_failure_requires_reconciliation(api):
    client,db=api; case=ready(client,True); db.invoices.fail_insert=True
    response=client.post(f"/api/invoice-readiness-cases/{case['id']}/invoice",json={"version":3},headers={**h("owner"),"Idempotency-Key":"fail-invoice"})
    assert response.status_code==503 and db.operations.docs[0]["status"]=="reconciliation_required" and len(db.reconciliation_items.docs)==1
    assert client.post(f"/api/invoice-readiness-cases/{case['id']}/invoice",json={"version":4},headers={**h("owner"),"Idempotency-Key":"fail-invoice"}).status_code==409


def test_outbox_failure_after_invoice_requires_reconciliation(api):
    client,db=api; case=ready(client,True); db.outbox_events.fail_insert=True
    response=client.post(f"/api/invoice-readiness-cases/{case['id']}/invoice",json={"version":3},headers={**h("owner"),"Idempotency-Key":"fail-outbox"})
    assert response.status_code==503 and len(db.invoices.docs)==1 and db.operations.docs[0]["status"]=="reconciliation_required"
    assert db.invoice_readiness_cases.docs[0]["invoice_creation_state"]=="reconciliation_required" and len(db.reconciliation_items.docs)==1


def test_invoice_audit_start_failure_creates_no_operation_or_artifact(api):
    client,db=api; case=ready(client,True); db.audit_events.fail_insert=True
    response=client.post(f"/api/invoice-readiness-cases/{case['id']}/invoice",json={"version":3},headers={**h("owner"),"Idempotency-Key":"audit-fail"})
    assert response.status_code==503 and not db.operations.docs and not db.invoice_packages.docs and not db.invoices.docs and not db.outbox_events.docs


@pytest.mark.parametrize("current,requested",[
    ("succeeded","started"),("succeeded","failed"),("succeeded","committing"),
    ("reconciliation_required","succeeded"),("reconciliation_required","started"),
    ("failed","committing"),("failed","started"),("partial","succeeded"),
])
def test_illegal_operation_transitions_do_not_mutate_or_increment(current,requested):
    col=collection("operations"); stamp="2026-01-01T00:00:00+00:00"
    steps=[{"name":name,"status":"completed","started_at":stamp,"completed_at":stamp,"failure_code":None} for name in ("operation_started","readiness_claimed","package_created","invoice_created","readiness_finalized","outbox_recorded")]
    op={"id":"OP","tenant_id":TA,"operation_type":"invoice.create","status":current,"version":7,"steps":steps,"current_step":"outbox_recorded"};col.docs=[dict(op)]
    before=list(col.update_calls)
    with pytest.raises(ValueError,match="Illegal operation transition"):asyncio.run(transition(col,op,status=requested))
    assert op["version"]==7 and col.docs[0]["version"]==7 and col.update_calls==before


@sync_test
async def test_valid_operation_and_step_progression_and_regression_guards():
    col=collection("operations");op,_=await create_or_replay(col,tenant_id=TA,operation_type="invoice.create",target_type="invoice_readiness_case",target_id="R",idempotency_key=None,request_id="REQ",actor=USERS["owner"])
    op=await transition(col,op,step="readiness_claimed")
    version=op["version"]
    for illegal in ("pending","started","failed"):
        with pytest.raises(ValueError,match="Illegal operation step transition"):await transition(col,op,step="readiness_claimed",step_status=illegal)
        assert op["version"]==version
    failed=dict(op);failed["steps"]=[dict(x) for x in op["steps"]];failed["steps"][2]["status"]="failed"
    with pytest.raises(ValueError,match="Illegal operation step transition"):await transition(col,failed,step="package_created",step_status="completed")
    for step in ("package_created","invoice_created"):op=await transition(col,op,step=step)
    op=await transition(col,op,status="committing",step="readiness_finalized")
    op=await transition(col,op,status="succeeded",step="outbox_recorded",result_reference={"invoice_id":"I","package_id":"P"})
    assert op["status"]=="succeeded" and op["version"]==6


def test_raced_successful_replay_exits_after_create_or_replay(api):
    client,db=api;case=ready(client,True);stale_case=copy.deepcopy(case);headers={**h("owner"),"Idempotency-Key":"raced-replay"}
    winner=client.post(f"/api/invoice-readiness-cases/{case['id']}/invoice",json={"version":3},headers=headers)
    winner_operation=copy.deepcopy(db.operations.docs[0]);updates_before=len(db.invoice_readiness_cases.update_calls)
    original=db.operations.find_one;hidden=True
    async def miss_initial(query,*args):
        nonlocal hidden
        if hidden and query.get("idempotency_key")=="raced-replay":hidden=False;return None
        return await original(query,*args)
    db.operations.find_one=miss_initial
    original_case=db.invoice_readiness_cases.find_one;stale_visible=True
    async def stale_initial_case(query,*args):
        nonlocal stale_visible
        if stale_visible and query.get("id")==case["id"]:stale_visible=False;return copy.deepcopy(stale_case)
        return await original_case(query,*args)
    db.invoice_readiness_cases.find_one=stale_initial_case
    replay=client.post(f"/api/invoice-readiness-cases/{case['id']}/invoice",json={"version":3},headers=headers)
    assert winner.status_code==replay.status_code==201 and replay.json()["id"]==winner.json()["id"]
    assert len(db.operations.docs)==len(db.invoice_packages.docs)==len(db.invoices.docs)==len(db.outbox_events.docs)==1
    assert db.operations.docs[0]==winner_operation and len(db.invoice_readiness_cases.update_calls)==updates_before and not db.reconciliation_items.docs
    phases=[(x["operation_id"],x["phase"],x.get("reason_code")) for x in db.audit_events.docs]
    assert phases.count((winner_operation["id"],"succeeded",""))==1 and phases[-1][1:]==("rejected","idempotent_replay")


def _fail_final_operation_update(db, *, also_reconciliation_transition=False):
    original=db.operations.update_one
    async def injected(query,update,**kwargs):
        requested=update.get("$set",{}).get("status")
        if requested=="succeeded" or (also_reconciliation_transition and requested=="reconciliation_required"):
            db.operations.events.append("operations.update");db.operations.update_calls.append((copy.deepcopy(query),copy.deepcopy(update)))
            return SimpleNamespace(matched_count=0,modified_count=0)
        return await original(query,update,**kwargs)
    db.operations.update_one=injected


def test_final_operation_success_failure_preserves_boundary_and_blocks_all_retries(api):
    client,db=api;case=ready(client,True);_fail_final_operation_update(db);headers={**h("owner"),"Idempotency-Key":"final-fail"}
    response=client.post(f"/api/invoice-readiness-cases/{case['id']}/invoice",json={"version":3},headers=headers)
    assert response.status_code==503 and len(db.invoice_packages.docs)==len(db.invoices.docs)==len(db.outbox_events.docs)==1
    assert db.operations.docs[0]["status"]=="reconciliation_required" and len(db.reconciliation_items.docs)==1
    for retry_headers in (headers,{**h("owner"),"Idempotency-Key":"different-key"},h("owner")):
        assert client.post(f"/api/invoice-readiness-cases/{case['id']}/invoice",json={"version":3},headers=retry_headers).status_code==409
    assert len(db.operations.docs)==len(db.invoice_packages.docs)==len(db.invoices.docs)==len(db.outbox_events.docs)==1
    assert not any(x.get("phase")=="succeeded" for x in db.audit_events.docs if x.get("action")=="invoice.created")


def test_finalization_and_reconciliation_write_failure_remains_stranded_and_detectable(api):
    client,db=api;case=ready(client,True);_fail_final_operation_update(db,also_reconciliation_transition=True);db.reconciliation_items.fail_insert=True
    response=client.post(f"/api/invoice-readiness-cases/{case['id']}/invoice",json={"version":3},headers={**h("owner"),"Idempotency-Key":"stranded"})
    assert response.status_code==503 and len(db.invoice_packages.docs)==len(db.invoices.docs)==len(db.outbox_events.docs)==1 and not db.reconciliation_items.docs
    assert db.operations.docs[0]["status"]=="committing"
    records={"tenants":[{"id":TA}],"operations":db.operations.docs,"outbox_events":db.outbox_events.docs,"reconciliation_items":[],"invoices":db.invoices.docs,"invoice_packages":db.invoice_packages.docs,"invoice_readiness_cases":db.invoice_readiness_cases.docs}
    report=scan_integrity(records,generated_at="2026-01-01T00:00:00+00:00")
    assert "OPERATION_STRANDED_AFTER_OUTBOX" in {x["code"] for x in report["findings"]}


def _operation(oid,tenant=TA,key=None,operation_type="invoice.create",target="R"):
    return {"id":oid,"tenant_id":tenant,"operation_type":operation_type,"target_type":"invoice_readiness_case","target_id":target,"idempotency_key":key,"status":"started","version":1}


def _collision_codes(operations):
    report=scan_integrity({"tenants":[{"id":TA},{"id":TB}],"operations":operations},generated_at="2026-01-01T00:00:00+00:00")
    return [x for x in report["findings"] if x["code"]=="INDEX_COLLISION" and "uq_operations_idempotency_identity" in x["description"]]


def test_optional_idempotency_index_excludes_null_and_missing_keys():
    first=_operation("A");second=_operation("B");second.pop("idempotency_key")
    assert not _collision_codes([first,second])


def test_optional_idempotency_index_collides_only_for_same_valid_identity():
    assert _collision_codes([_operation("A",key="K"),_operation("B",key="K")])
    assert not _collision_codes([_operation("A",TA,"K"),_operation("B",TB,"K")])
    assert not _collision_codes([_operation("A",key="K"),_operation("B",key="K",operation_type="invoice.cancel")])
    assert not _collision_codes([_operation("A",key="K",target="R1"),_operation("B",key="K",target="R2")])
    with pytest.raises(ValueError):idempotency_identity(TA,"invoice.create","invoice_readiness_case","R","invalid key")
