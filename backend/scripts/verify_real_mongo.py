"""Fail-closed disposable real-Mongo staging certification.

The manifest plan is available without a connection. Execution never falls back to
the application database and only mutates an initially empty, explicitly confirmed
disposable database. The harness owns everything it creates and drops that database
on cleanup.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from pymongo.errors import ConfigurationError, DuplicateKeyError, InvalidOperation, OperationFailure

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.index_manifest import compare_indexes, expected_indexes

TEST_DB = re.compile(r"^(?:test_|.*_(?:test|testing|disposable))$", re.I)
TRUE = {"1", "true", "yes", "confirmed"}
PREFIX = "phase2g-cert-"


def _operation_failure_report(exc, stage, context=None):
    """Return only bounded Mongo metadata; never serialize exception text/details."""
    details = exc.details if isinstance(getattr(exc, "details", None), dict) else {}
    report = {
        "status": "FAIL", "reason_code": "OperationFailure", "stage": stage,
        "mongo_error_code": getattr(exc, "code", None),
        "mongo_error_code_name": getattr(exc, "code_name", None) or details.get("codeName"),
        "production_accessed": False, "customer_data_accessed": False, "uri_included": False,
    }
    for key in ("collection", "index_name"):
        if context and context.get(key):
            report[key] = context[key]
    return report


def guarded_target(env):
    uri = str(env.get("METAPHORA_TEST_MONGO_URI", "")).strip()
    db_name = str(env.get("METAPHORA_TEST_MONGO_DB", "")).strip()
    if not uri:
        raise ValueError("METAPHORA_TEST_MONGO_URI is required; no fallback is permitted")
    if not db_name or not TEST_DB.fullmatch(db_name):
        raise ValueError("METAPHORA_TEST_MONGO_DB must be clearly test/disposable")
    if str(env.get("APP_ENV", "")).strip().lower() not in {"test", "staging"}:
        raise ValueError("APP_ENV must explicitly be test or staging; production is forbidden")
    if str(env.get("METAPHORA_TEST_MONGO_DISPOSABLE_CONFIRMED", "")).strip().lower() not in TRUE:
        raise ValueError("operator must explicitly confirm the target contains no customer data and is disposable")
    parsed = urlsplit(uri)
    if parsed.scheme not in {"mongodb", "mongodb+srv"} or not parsed.hostname:
        raise ValueError("invalid test Mongo URI")
    return uri, db_name


def index_plan():
    return [{"collection": x.collection, "name": x.name, "fields": list(x.fields),
             "unique": x.unique, "partial_filter": x.partial_filter, "priority": x.priority,
             "purpose": x.purpose} for x in expected_indexes()]


def validate_plan(plan=None):
    plan = index_plan() if plan is None else plan
    identities = [(x["collection"], x["name"]) for x in plan]
    duplicates = sorted({x for x in identities if identities.count(x) > 1})
    invalid = [x["name"] for x in plan if not x["fields"] or any(v not in (1, -1) for _, v in x["fields"])]
    return {"status": "PASS" if not duplicates and not invalid else "FAIL",
            "index_count": len(plan), "duplicates": duplicates, "invalid": invalid, "indexes": plan}


def _observed(specs):
    return [{"name": x["name"], "fields": list(x["key"].items()), "unique": x.get("unique", False),
             "partial_filter": x.get("partialFilterExpression")} for x in specs]


async def _expect_duplicate(collection, first, second):
    await collection.insert_one(first)
    try:
        await collection.insert_one(second)
    except DuplicateKeyError:
        return True
    return False


async def _unique_semantics(db):
    results = {}
    # Login email is globally unique in the current architecture; tenant entity identity is separately scoped.
    results["email_global_duplicate_rejected"] = await _expect_duplicate(
        db.users, {"id": PREFIX+"u1", "tenant_id": PREFIX+"t1", "email": "pilot@example.test"},
        {"id": PREFIX+"u2", "tenant_id": PREFIX+"t2", "email": "pilot@example.test"})
    base = {"tenant_id": PREFIX+"t1", "active_identity": "same"}
    await db.action_items.insert_one({**base, "id": PREFIX+"resolved", "status": "resolved"})
    results["action_active_duplicate_rejected"] = await _expect_duplicate(
        db.action_items, {**base, "id": PREFIX+"open", "status": "open"},
        {**base, "id": PREFIX+"ack", "status": "acknowledged"})
    results["action_resolved_recurrence_allowed"] = await db.action_items.count_documents(base) == 2
    ebase = {"tenant_id": PREFIX+"t1", "load_id": PREFIX+"load"}
    results["execution_active_duplicate_rejected"] = await _expect_duplicate(
        db.execution_sessions, {**ebase, "id": PREFIX+"e1", "status": "active"},
        {**ebase, "id": PREFIX+"e2", "status": "pending_start"})
    await db.execution_sessions.update_one({"id": PREFIX+"e1"}, {"$set": {"status": "completed"}})
    await db.execution_sessions.insert_one({**ebase, "id": PREFIX+"e3", "status": "completed"})
    results["execution_terminal_history_allowed"] = True
    op = {"tenant_id": PREFIX+"t1", "operation_type": "cert", "target_type": "load",
          "target_id": PREFIX+"load", "idempotency_key": "same"}
    results["operation_duplicate_rejected"] = await _expect_duplicate(
        db.operations, {**op, "id": PREFIX+"op1"}, {**op, "id": PREFIX+"op2"})
    await db.operations.insert_one({**{k:v for k,v in op.items() if k != "idempotency_key"}, "id": PREFIX+"op3"})
    await db.operations.insert_one({**{k:v for k,v in op.items() if k != "idempotency_key"}, "id": PREFIX+"op4", "idempotency_key": None})
    results["operation_missing_and_null_allowed"] = True
    results["invoice_authority_duplicate_rejected"] = await _expect_duplicate(
        db.invoices, {"id": PREFIX+"i1", "tenant_id": PREFIX+"t1", "readiness_case_id": PREFIX+"r"},
        {"id": PREFIX+"i2", "tenant_id": PREFIX+"t1", "readiness_case_id": PREFIX+"r"})
    results["package_authority_duplicate_rejected"] = await _expect_duplicate(
        db.invoice_packages, {"id": PREFIX+"p1", "tenant_id": PREFIX+"t1", "readiness_case_id": PREFIX+"r"},
        {"id": PREFIX+"p2", "tenant_id": PREFIX+"t1", "readiness_case_id": PREFIX+"r"})
    return results


async def _concurrency(db, stage):
    stage["name"] = "concurrency_action_center"
    async def insert_action(n):
        try:
            await db.action_items.insert_one({"id": f"{PREFIX}race-a{n}", "tenant_id": PREFIX+"race",
                "active_identity": "one", "status": "open"}); return True
        except DuplicateKeyError: return False
    action = await asyncio.gather(*(insert_action(n) for n in range(8)))

    stage["name"] = "concurrency_outbox"
    await db.outbox_events.insert_one({"id": PREFIX+"outbox", "tenant_id": PREFIX+"race", "operation_id": PREFIX+"op",
        "event_type": "cert", "aggregate_type": "load", "aggregate_id": PREFIX+"load", "status": "pending"})
    now = datetime.now(timezone.utc)
    async def lease(n):
        token=f"token-{n}"
        doc=await db.outbox_events.find_one_and_update(
            {"id": PREFIX+"outbox", "status": "pending"},
            {"$set":{"status":"claimed", "claim_token":token, "claim_expires_at":now+timedelta(minutes=1)}},
            return_document=ReturnDocument.AFTER)
        return token if doc else None
    leases = await asyncio.gather(*(lease(n) for n in range(8)))
    winner = next((x for x in leases if x), None)
    stale = await db.outbox_events.update_one({"id": PREFIX+"outbox", "claim_token":"stale"}, {"$set":{"status":"sent"}})
    valid = await db.outbox_events.update_one({"id": PREFIX+"outbox", "claim_token":winner}, {"$set":{"status":"sent"}})

    async def race_insert(collection, doc):
        async def attempt(n):
            try: await collection.insert_one({**doc, "id": f"{doc['id']}{n}"}); return True
            except DuplicateKeyError: return False
        return sum(await asyncio.gather(*(attempt(n) for n in range(8))))
    stage["name"] = "concurrency_operation"
    operation_winners = await race_insert(db.operations, {"id":PREFIX+"race-op", "tenant_id":PREFIX+"race",
        "operation_type":"cert", "target_type":"load", "target_id":"one", "idempotency_key":"one"})
    stage["name"] = "concurrency_invoice"
    invoice_winners = await race_insert(db.invoices, {"id":PREFIX+"race-inv", "tenant_id":PREFIX+"race", "readiness_case_id":"one"})
    stage["name"] = "concurrency_execution"
    execution_winners = await race_insert(db.execution_sessions, {"id":PREFIX+"race-exe", "tenant_id":PREFIX+"race",
        "load_id":"one", "status":"active"})
    result={"action_center_winners":sum(action), "outbox_lease_winners":sum(x is not None for x in leases),
            "outbox_stale_finalize_rejected":stale.modified_count == 0, "outbox_winner_finalize":valid.modified_count == 1,
            "operation_winners":operation_winners, "invoice_winners":invoice_winners, "execution_winners":execution_winners}
    result["status"]="PASS" if all((result["action_center_winners"]==1, result["outbox_lease_winners"]==1,
        result["outbox_stale_finalize_rejected"], result["outbox_winner_finalize"], operation_winners==1,
        invoice_winners==1, execution_winners==1)) else "FAIL"
    return result


async def verify(env, client_factory=AsyncIOMotorClient):
    stage = {"name": "guard_target", "context": {}}
    uri, db_name = guarded_target(env)
    stage["name"] = "connect"
    client = client_factory(uri, serverSelectionTimeoutMS=4000)
    cleanup = "NOT_STARTED"
    owned = False
    report = None
    try:
        stage["name"] = "hello"
        hello = await client.admin.command("hello")
        db = client[db_name]
        stage["name"] = "target_empty_check"
        collections = await db.list_collection_names()
        if collections:
            raise RuntimeError("target database is not empty; harness ownership cannot be proven")
        owned = True
        stage["name"] = "manifest_validation"
        plan = validate_plan()
        if plan["status"] != "PASS": raise RuntimeError("index manifest dry validation failed")
        created=[]
        for index in expected_indexes():
            stage["name"] = "index_creation"
            stage["context"] = {"collection": index.collection, "index_name": index.name}
            options={"name":index.name, "unique":index.unique}
            if index.partial_filter: options["partialFilterExpression"]=index.partial_filter
            await db[index.collection].create_index(list(index.fields), **options); created.append(index.name)
        stage["name"] = "index_comparison"
        stage["context"] = {}
        observed={c:_observed(await db[c].list_indexes().to_list(length=200)) for c in sorted({x.collection for x in expected_indexes()})}
        comparison=compare_indexes(observed)
        stage["name"] = "topology_probe"
        topology = "sharded_cluster" if hello.get("msg") == "isdbgrid" else "replica_set" if hello.get("setName") else "standalone"
        sessions = hello.get("logicalSessionTimeoutMinutes") is not None
        transaction="UNSUPPORTED_TOPOLOGY"
        if sessions and topology in {"replica_set", "sharded_cluster"}:
            stage["name"] = "transaction_probe"
            session=await client.start_session()
            try:
                session.start_transaction()
                await db.phase2g_probe.insert_many([{"_id":"abort-a"},{"_id":"abort-b"}], session=session)
                await session.abort_transaction()
                if await db.phase2g_probe.count_documents({"_id":{"$in":["abort-a","abort-b"]}}): raise RuntimeError("transaction abort probe failed")
                session.start_transaction()
                await db.phase2g_probe.insert_many([{"_id":"commit-a"},{"_id":"commit-b"}], session=session)
                await session.commit_transaction()
                if await db.phase2g_probe.count_documents({"_id":{"$in":["commit-a","commit-b"]}}) != 2: raise RuntimeError("transaction commit probe failed")
                transaction="SUPPORTED_COMMIT_ABORT_VERIFIED"
            except (ConfigurationError, InvalidOperation): transaction="UNSUPPORTED_TOPOLOGY"
            finally: await session.end_session()
        stage["name"] = "unique_semantics"
        semantics=await _unique_semantics(db)
        concurrency=await _concurrency(db, stage)
        ok=not comparison["missing"] and not comparison["mismatched"] and all(semantics.values()) and concurrency["status"]=="PASS"
        stage["name"] = "build_info"
        build_info=await client.admin.command("buildInfo")
        report={"status":"PASS" if ok else "FAIL", "database_classification":"DISPOSABLE_TEST",
            "mongo_version":build_info.get("version", "unknown"), "topology":topology, "sessions_supported":sessions,
            "transaction_capability":transaction, "pilot_uow_mode":"durable_saga", "index_plan_status":plan["status"],
            "indexes":{"created":created, **comparison}, "unique_semantics":semantics, "concurrency":concurrency,
            "production_accessed":False, "customer_data_accessed":False, "uri_included":False}
    except OperationFailure as exc:
        report = _operation_failure_report(exc, stage["name"], stage["context"])
    finally:
        if owned:
            try:
                stage["name"] = "cleanup"
                await client.drop_database(db_name); cleanup="OWNED_DISPOSABLE_DATABASE_DROPPED"
            except OperationFailure as exc:
                cleanup="OWNED_DISPOSABLE_DATABASE_CLEANUP_FAILED"
                cleanup_error=_operation_failure_report(exc, "cleanup")
                if report is None or report.get("status") == "PASS": report=cleanup_error
                else: report["cleanup_error"]={k:cleanup_error[k] for k in ("stage","mongo_error_code","mongo_error_code_name")}
        else:
            cleanup="NOT_OWNED_NO_DROP"
        if report is not None: report["cleanup_result"] = cleanup
        client.close()
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(); parser.add_argument("--json", action="store_true"); parser.add_argument("--plan", action="store_true")
    args=parser.parse_args(argv)
    if args.plan:
        report=validate_plan()
    else:
        try: report=asyncio.run(verify(os.environ))
        except (ValueError, RuntimeError) as exc:
            report={"status":"NOT_EXECUTED", "reason":str(exc), "required":"REAL MONGO CERTIFICATION REQUIRES EXPLICIT DISPOSABLE URI",
                    "production_accessed":False, "customer_data_accessed":False, "uri_included":False}
        except Exception as exc:
            report={"status":"FAIL", "reason_code":exc.__class__.__name__,
                    "reason":"bounded Mongo certification failure; inspect redacted operator logs",
                    "production_accessed":False, "customer_data_accessed":False, "uri_included":False}
    print(json.dumps(report, sort_keys=True) if args.json else f"REAL-MONGO: {report['status']}")
    return 0 if report["status"]=="PASS" else 2


if __name__ == "__main__": raise SystemExit(main())
