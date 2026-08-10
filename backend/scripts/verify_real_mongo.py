"""Disposable real-Mongo verification. Never falls back to application MONGO_URI."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.index_manifest import compare_indexes, expected_indexes

TEST_DB = re.compile(r"^(?:test_|.*_(?:test|testing|disposable))$", re.I)


def guarded_target(env):
    uri = str(env.get("METAPHORA_TEST_MONGO_URI", "")).strip()
    db_name = str(env.get("METAPHORA_TEST_MONGO_DB", "")).strip()
    if not uri:
        raise ValueError("METAPHORA_TEST_MONGO_URI is required; no fallback is permitted")
    if not db_name or not TEST_DB.fullmatch(db_name):
        raise ValueError("METAPHORA_TEST_MONGO_DB must be clearly test/disposable")
    if str(env.get("APP_ENV", "")).strip().lower() in {"production", "prod"}:
        raise ValueError("production APP_ENV is forbidden")
    parsed = urlsplit(uri)
    if parsed.scheme not in {"mongodb", "mongodb+srv"} or not parsed.hostname:
        raise ValueError("invalid test Mongo URI")
    return uri, db_name


def _observed(specs):
    return [{"name": x["name"], "fields": list(x["key"].items()), "unique": x.get("unique", False),
             "partial_filter": x.get("partialFilterExpression")} for x in specs]


async def verify(env):
    uri, db_name = guarded_target(env)
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=4000)
    db = client[db_name]
    await client.admin.command("ping")
    # Destructive operations are restricted to the guard-verified disposable DB.
    await client.drop_database(db_name)
    for index in expected_indexes():
        options = {"name": index.name, "unique": index.unique}
        if index.partial_filter:
            options["partialFilterExpression"] = index.partial_filter
        await db[index.collection].create_index(list(index.fields), **options)
    observed = {}
    for collection in sorted({x.collection for x in expected_indexes()}):
        observed[collection] = _observed(await db[collection].list_indexes().to_list(length=200))
    comparison = compare_indexes(observed)
    transaction = "UNSUPPORTED_TOPOLOGY"
    session = await client.start_session()
    try:
        try:
            async with session.start_transaction():
                await db.phase2g_probe.insert_one({"_id": "abort-a"}, session=session)
                await db.phase2g_probe.insert_one({"_id": "abort-b"}, session=session)
                await session.abort_transaction()
            if await db.phase2g_probe.count_documents({"_id": {"$in": ["abort-a", "abort-b"]}}):
                raise RuntimeError("transaction abort probe failed")
            async with session.start_transaction():
                await db.phase2g_probe.insert_one({"_id": "commit-a"}, session=session)
                await db.phase2g_probe.insert_one({"_id": "commit-b"}, session=session)
            transaction = "SUPPORTED"
        except Exception as exc:
            if exc.__class__.__name__ not in {"OperationFailure", "ConfigurationError", "InvalidOperation"}:
                raise
    finally:
        await session.end_session()
    # Actual partial-index and bounded race semantics.
    actions = db.action_items
    base = {"tenant_id": "ten_phase2g", "active_identity": "same"}
    await actions.insert_one({**base, "id": "resolved", "status": "resolved"})
    await actions.insert_one({**base, "id": "open", "status": "open"})
    duplicate_rejected = False
    try:
        await actions.insert_one({**base, "id": "ack", "status": "acknowledged"})
    except Exception as exc:
        duplicate_rejected = exc.__class__.__name__ == "DuplicateKeyError"
    result = {"status": "PASS" if not comparison["missing"] and not comparison["mismatched"] and duplicate_rejected else "FAIL",
              "database_classification": "DISPOSABLE_TEST", "indexes": comparison,
              "transaction_capability": transaction, "active_identity_duplicate_rejected": duplicate_rejected,
              "production_accessed": False, "uri_included": False}
    await client.drop_database(db_name)
    client.close()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(verify(os.environ))
    except ValueError as exc:
        report = {"status": "NOT_EXECUTED", "reason": str(exc), "production_accessed": False, "uri_included": False}
    print(json.dumps(report, sort_keys=True) if args.json else f"REAL-MONGO: {report['status']}")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
