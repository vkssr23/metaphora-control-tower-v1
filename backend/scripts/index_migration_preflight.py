"""Read-only preflight for rolling out the Mongo index manifest to production.

Classifies every manifest entry (unique/idempotency, partial/sparse, TTL,
ordinary performance) with no DB access, then — given a DB — reports document
counts, collStats size estimates, and unique-index conflict *counts* using
only metadata and aggregation reads: list_collection_names(), an
$group/$match/$count aggregation pipeline, estimated_document_count(), and
the collStats command. No create_index, insert, update, delete, drop, or
migration call anywhere in this module. A missing collection is reported as
zero documents/no conflicts, never created.

Conflict counts only ever surface a number ("N groups of duplicate keys");
the grouped key values themselves are discarded, never returned or printed,
so this cannot leak tenant/business data even indirectly.
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

from app.infrastructure.index_manifest import IndexDefinition, expected_indexes

SERVER_SELECTION_TIMEOUT_MS = 4000
CONNECT_TIMEOUT_MS = 4000


# ---- Pure classification (no DB access) -----------------------------------

def classify(index: IndexDefinition) -> dict:
    return {
        "collection": index.collection,
        "name": index.name,
        "category": "unique_idempotency" if index.unique else "performance",
        "partial": index.partial_filter is not None,
        "ttl": False,  # the manifest schema has no expireAfterSeconds concept today
        "priority": index.priority,
    }


def classify_manifest() -> list[dict]:
    return [classify(x) for x in expected_indexes()]


REQUIRED_IMMEDIATELY = {
    "login_email_uniqueness": ("users", "uq_users_email"),
    "verify_to_control_tower_sso_tenant_idempotency": ("tenants", "uq_tenants_metaphora_org_id"),
    "tenant_isolation_security": ("users", "uq_users_tenant_id_id"),
}
# No manifest entry exists for token expiry/replay protection: JWTs are
# stateless (exp claim) and Verify's own token_valid_after staleness check is
# a Postgres-side lookup, not a Mongo TTL index — flagged as a gap, not a name.


def staged_migration_order() -> dict[str, list[str]]:
    entries = classify_manifest()
    critical = sorted(x["name"] for x in entries if x["category"] == "unique_idempotency")
    ttl = sorted(x["name"] for x in entries if x["ttl"])
    performance = sorted(x["name"] for x in entries if x["category"] == "performance")
    return {"stage_1_critical_unique_security": critical, "stage_2_ttl": ttl, "stage_3_performance": performance}


# ---- Read-only DB preflight -------------------------------------------------

def _mongo_field(field: str) -> str:
    return f"${field}"


async def _conflict_group_count(collection, index: IndexDefinition) -> int:
    """Count groups sharing the same unique-key components, honoring the
    index's own partial filter. Returns a count only — never the keys."""
    pipeline: list[dict[str, Any]] = []
    if index.partial_filter:
        pipeline.append({"$match": index.partial_filter})
    group_id = {field: _mongo_field(field) for field, _ in index.fields}
    pipeline.append({"$group": {"_id": group_id, "n": {"$sum": 1}}})
    pipeline.append({"$match": {"n": {"$gt": 1}}})
    pipeline.append({"$count": "conflicts"})
    result = await collection.aggregate(pipeline).to_list(length=1)
    return result[0]["conflicts"] if result else 0


async def run_preflight(mongo_url: str, db_name: str, client_factory: Callable = AsyncIOMotorClient) -> dict:
    client = client_factory(mongo_url, serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS, connectTimeoutMS=CONNECT_TIMEOUT_MS)
    try:
        db = client[db_name]
        existing = set(await db.list_collection_names())
        collections = sorted({x.collection for x in expected_indexes()})

        document_counts: dict[str, int] = {}
        size_estimates: dict[str, dict[str, int]] = {}
        for name in collections:
            if name not in existing:
                document_counts[name] = 0
                size_estimates[name] = {"storage_size_bytes": 0, "avg_obj_size_bytes": 0}
                continue
            document_counts[name] = await db[name].estimated_document_count()
            stats = await db.command("collStats", name)
            size_estimates[name] = {
                "storage_size_bytes": int(stats.get("storageSize", 0)),
                "avg_obj_size_bytes": int(stats.get("avgObjSize", 0)),
            }

        unique_conflicts = []
        for index in expected_indexes():
            if not index.unique or index.collection not in existing:
                continue
            n = await _conflict_group_count(db[index.collection], index)
            if n:
                unique_conflicts.append({"collection": index.collection, "name": index.name, "conflict_groups": n})

        return {
            "status": "BLOCKED" if unique_conflicts else "READY",
            "classification": classify_manifest(),
            "required_immediately": {k: {"collection": c, "name": n} for k, (c, n) in REQUIRED_IMMEDIATELY.items()},
            "staged_migration_order": staged_migration_order(),
            "document_counts": document_counts,
            "size_estimates": size_estimates,
            "unique_conflicts": unique_conflicts,
        }
    finally:
        client.close()


def main(argv: list[str] | None = None, environ: dict | None = None, client_factory: Callable = AsyncIOMotorClient) -> int:
    env = os.environ if environ is None else environ
    if argv and "--classify-only" in argv:
        print(json.dumps({"classification": classify_manifest(), "staged_migration_order": staged_migration_order()}, sort_keys=True))
        return 0
    mongo_url, db_name = env.get("MONGO_URL"), env.get("DB_NAME")
    if not mongo_url or not db_name:
        print(json.dumps({"status": "ERROR", "reason": "MONGO_URL and DB_NAME must both be set"}))
        return 2
    try:
        report = asyncio.run(run_preflight(mongo_url, db_name, client_factory))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason_code": exc.__class__.__name__}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
