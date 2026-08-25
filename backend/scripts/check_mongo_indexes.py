"""Read-only Mongo index inspector.

Compares the live indexes on MONGO_URL/DB_NAME against the declared manifest
in app.infrastructure.index_manifest. The only Mongo calls made are
list_collection_names() and list_indexes() — both metadata reads. This
module contains no create_index, insert, update, delete, drop, or migration
call anywhere; a collection missing entirely is treated as "no indexes
present" rather than being created.

Never prints MONGO_URL, DB_NAME, documents, or any field value from the
database — only collection names, index names, and normalized index
definitions (field/direction, unique, partial filter), all of which come
from the manifest or from list_indexes() metadata, not from documents.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from motor.motor_asyncio import AsyncIOMotorClient

from app.infrastructure.index_manifest import compare_indexes, expected_indexes

SERVER_SELECTION_TIMEOUT_MS = 4000
CONNECT_TIMEOUT_MS = 4000


def _observed(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": x["name"],
            "fields": list(x["key"].items()),
            "unique": x.get("unique", False),
            "partial_filter": x.get("partialFilterExpression"),
        }
        for x in specs
    ]


async def inspect_indexes(mongo_url: str, db_name: str, client_factory: Callable = AsyncIOMotorClient) -> dict:
    """Read-only: list_collection_names() + list_indexes() only. No writes."""
    client = client_factory(
        mongo_url,
        serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
        connectTimeoutMS=CONNECT_TIMEOUT_MS,
    )
    try:
        db = client[db_name]
        existing = set(await db.list_collection_names())
        observed: dict[str, list[dict[str, Any]]] = {}
        for collection in sorted({x.collection for x in expected_indexes()}):
            if collection not in existing:
                observed[collection] = []
                continue
            specs = await db[collection].list_indexes().to_list(length=200)
            observed[collection] = _observed(specs)
        comparison = compare_indexes(observed)
        status = "PASS" if not comparison["missing"] and not comparison["mismatched"] else "DRIFT"
        return {"status": status, "collections_checked": sorted(observed.keys()), **comparison}
    finally:
        client.close()


def main(argv: list[str] | None = None, environ: dict | None = None, client_factory: Callable = AsyncIOMotorClient) -> int:
    env = os.environ if environ is None else environ
    mongo_url = env.get("MONGO_URL")
    db_name = env.get("DB_NAME")
    if not mongo_url or not db_name:
        print(json.dumps({"status": "ERROR", "reason": "MONGO_URL and DB_NAME must both be set"}))
        return 2
    try:
        report = asyncio.run(inspect_indexes(mongo_url, db_name, client_factory))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason_code": exc.__class__.__name__}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
