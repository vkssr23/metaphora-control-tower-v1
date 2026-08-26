"""Create-only, idempotent apply tool for exactly three critical indexes:

  uq_users_email, uq_tenants_metaphora_org_id, uq_users_tenant_id_id

--plan (default): prints the three exact manifest definitions. No DB access.

--apply requires --confirm CREATE_CRITICAL_INDEXES_V1 (checked before any
client is constructed). Before any write, it reruns the same bounded
conflict/multikey/collation checks as index_migration_preflight.py using
the manifest's current (corrected) definitions, plus a drift check: an
index with the same name but a different definition already present is
never touched — creation aborts entirely, for all three, rather than risk
silently living with (or worse, altering) an unexpected definition.

Only if every one of the three checks out clean does it create the missing
ones, one at a time, in the fixed order above. After each create_index call
it reads the index back via list_indexes() and verifies name/keys/unique/
partial filter match exactly. An index already present with the correct
definition is skipped (idempotent). No drop_index/replace/modify call
exists anywhere in this module — a failure partway through (or a prior
partial run) is safe to resume: already-created/matching indexes are
detected and skipped, never recreated or rolled back.

Never prints document field values, credentials, or environment values —
only index metadata (names/fields/unique/partial filter, which are public
schema, not data) and booleans/counts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError

from app.infrastructure.index_manifest import compare_indexes, expected_indexes
from scripts.index_migration_preflight import (
    DEFAULT_MAX_TIME_MS,
    MAX_ALLOWED_MAX_TIME_MS,
    PreflightTimeout,
    _conflict_group_count,
    _has_array_values,
    reject_unmodeled_collation,
    resolve_max_time_ms,
)

CRITICAL_INDEX_NAMES = ("uq_users_email", "uq_tenants_metaphora_org_id", "uq_users_tenant_id_id")
CONFIRMATION = "CREATE_CRITICAL_INDEXES_V1"


def _critical_indexes():
    by_name = {x.name: x for x in expected_indexes()}
    return [by_name[name] for name in CRITICAL_INDEX_NAMES]


def _plan() -> dict:
    return {
        "status": "PLAN",
        "indexes": [
            {"collection": x.collection, "name": x.name, "fields": list(x.fields),
             "unique": x.unique, "partial_filter": x.partial_filter}
            for x in _critical_indexes()
        ],
    }


def _observed(specs):
    return [{"name": x["name"], "fields": list(x["key"].items()), "unique": x.get("unique", False),
             "partial_filter": x.get("partialFilterExpression")} for x in specs]


async def _validate(db, max_time_ms: int) -> dict:
    """Read-only. Returns {"ok": bool, "per_index": {...}} — never values."""
    indexes = _critical_indexes()
    for index in indexes:
        reject_unmodeled_collation(index)

    collections = sorted({x.collection for x in indexes})
    existing_collections = set(await db.list_collection_names())
    observed = {}
    for collection in collections:
        if collection not in existing_collections:
            observed[collection] = []
            continue
        try:
            specs = await db[collection].list_indexes().to_list(length=200)
        except PyMongoError as exc:
            raise PreflightTimeout("list_indexes", collection) from exc
        observed[collection] = _observed(specs)
    comparison = compare_indexes(observed)
    missing_names = {m["name"] for m in comparison["missing"]}
    mismatched_names = {m["name"] for m in comparison["mismatched"]}

    per_index = {}
    ok = True
    for index in indexes:
        conflict_groups = 0
        multikey = False
        if index.collection in existing_collections:
            conflict_groups = await _conflict_group_count(db[index.collection], index, max_time_ms)
            for field, _ in index.fields:
                if await _has_array_values(db[index.collection], field, max_time_ms):
                    multikey = True
                    break
        if index.name in mismatched_names:
            state = "DRIFT"
        elif index.name in missing_names:
            state = "MISSING"
        else:
            state = "MATCHES"
        clean = state != "DRIFT" and conflict_groups == 0 and not multikey
        ok = ok and clean
        per_index[index.name] = {"state": state, "conflict_groups": conflict_groups, "multikey": multikey, "clean": clean}
    return {"ok": ok, "per_index": per_index}


async def apply(mongo_url: str, db_name: str, client_factory: Callable, max_time_ms: int) -> dict:
    client = client_factory(mongo_url, serverSelectionTimeoutMS=DEFAULT_MAX_TIME_MS, connectTimeoutMS=DEFAULT_MAX_TIME_MS)
    try:
        db = client[db_name]
        try:
            validation = await _validate(db, max_time_ms)
        except PreflightTimeout as exc:
            return {"status": "INCOMPLETE_UNSAFE", "reason": "operation_timeout", "stage": exc.stage, "collection": exc.collection}

        if not validation["ok"]:
            return {"status": "ABORT_VALIDATION_FAILED", "per_index": validation["per_index"]}

        created, skipped = [], []
        for index in _critical_indexes():
            state = validation["per_index"][index.name]["state"]
            if state == "MATCHES":
                skipped.append(index.name)
                continue
            options = {"name": index.name, "unique": index.unique}
            if index.partial_filter:
                options["partialFilterExpression"] = index.partial_filter
            try:
                await db[index.collection].create_index(list(index.fields), **options)
                specs = await db[index.collection].list_indexes().to_list(length=200)
            except PyMongoError as exc:
                return {
                    "status": "PARTIAL_FAILURE", "reason_code": exc.__class__.__name__,
                    "failed_index": index.name, "created_so_far": created, "skipped_already_present": skipped,
                }
            observed = next((x for x in _observed(specs) if x["name"] == index.name), None)
            verified = bool(
                observed and tuple(tuple(f) for f in observed["fields"]) == index.fields
                and observed["unique"] == index.unique and observed["partial_filter"] == index.partial_filter
            )
            if not verified:
                return {
                    "status": "PARTIAL_FAILURE", "reason": "post_create_verification_mismatch",
                    "failed_index": index.name, "created_so_far": created, "skipped_already_present": skipped,
                }
            created.append(index.name)

        return {"status": "COMPLETE", "created": created, "skipped_already_present": skipped}
    finally:
        client.close()


def main(argv: list[str] | None = None, environ: dict | None = None, client_factory: Callable = AsyncIOMotorClient) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default=None)
    args = parser.parse_args(argv if argv is not None else [])

    if not args.apply:
        print(json.dumps(_plan(), sort_keys=True))
        return 0

    if args.confirm != CONFIRMATION:
        print(json.dumps({"status": "ABORT_CONFIRMATION_REQUIRED"}))
        return 2

    env = os.environ if environ is None else environ
    mongo_url, db_name = env.get("MONGO_URL"), env.get("DB_NAME")
    if not mongo_url or not db_name:
        print(json.dumps({"status": "ERROR", "reason": "MONGO_URL and DB_NAME must both be set"}))
        return 2
    max_time_ms = resolve_max_time_ms(env)

    try:
        report = asyncio.run(apply(mongo_url, db_name, client_factory, max_time_ms))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason_code": exc.__class__.__name__}))
        return 2

    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
