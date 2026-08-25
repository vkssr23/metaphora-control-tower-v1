"""Read-only preflight for rolling out the Mongo index manifest to production.

Classifies every manifest entry (unique/idempotency, partial/sparse, TTL,
ordinary performance) with no DB access, then — given a DB — reports document
counts, collStats size estimates, and unique-index conflict *counts* using
only metadata and aggregation reads: list_collection_names(), an
$group/$match/$count aggregation pipeline, estimated_document_count(), a
bounded $type:"array" existence count per unique field, and the collStats
command. No create_index, insert, update, delete, drop, or migration call
anywhere in this module. A missing collection is reported as zero
documents/no conflicts, never created.

Every potentially scanning operation (aggregate, collStats,
estimated_document_count, the array-detection count) is given an explicit,
bounded maxTimeMS. If the server enforces that timeout, the whole run stops
and reports status INCOMPLETE_UNSAFE with a nonzero exit — never a
misleading READY/BLOCKED built from partial data.

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
from pymongo.errors import PyMongoError

from app.infrastructure.index_manifest import IndexDefinition, expected_indexes

SERVER_SELECTION_TIMEOUT_MS = 4000
CONNECT_TIMEOUT_MS = 4000

# Per-operation cap on any single scanning read. Configurable (env var) but
# clamped so nothing — including a misconfigured operator override — can
# turn this into an unbounded production scan.
DEFAULT_MAX_TIME_MS = 4000
MAX_ALLOWED_MAX_TIME_MS = 15000


def resolve_max_time_ms(env: dict) -> int:
    raw = env.get("PREFLIGHT_MAX_TIME_MS")
    try:
        value = int(raw) if raw is not None else DEFAULT_MAX_TIME_MS
    except (TypeError, ValueError):
        value = DEFAULT_MAX_TIME_MS
    return max(1, min(value, MAX_ALLOWED_MAX_TIME_MS))


class PreflightTimeout(Exception):
    """Raised when a bounded read hits its maxTimeMS — never contains values."""
    def __init__(self, stage: str, collection: str | None = None, index_name: str | None = None):
        self.stage, self.collection, self.index_name = stage, collection, index_name
        super().__init__(stage)


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


# ---- Collation guard (no DB access) ----------------------------------------

# The checker models nothing beyond MongoDB's default ("simple", binary)
# collation. Any manifest index declaring anything else must be rejected
# rather than silently conflict-checked with the wrong comparison semantics.
MODELED_COLLATIONS = (None,)


def reject_unmodeled_collation(index: IndexDefinition) -> None:
    collation = getattr(index, "collation", None)
    if collation not in MODELED_COLLATIONS:
        raise ValueError(f"index {index.name} declares a collation the checker does not model: {collation!r}")


# ---- Read-only DB preflight -------------------------------------------------

def _mongo_field(field: str) -> str:
    return f"${field}"


async def _conflict_group_count(collection, index: IndexDefinition, max_time_ms: int) -> int:
    """Count groups sharing the same unique-key components, honoring the
    index's own partial filter. Returns a count only — never the keys."""
    pipeline: list[dict[str, Any]] = []
    if index.partial_filter:
        pipeline.append({"$match": index.partial_filter})
    group_id = {field: _mongo_field(field) for field, _ in index.fields}
    pipeline.append({"$group": {"_id": group_id, "n": {"$sum": 1}}})
    pipeline.append({"$match": {"n": {"$gt": 1}}})
    pipeline.append({"$count": "conflicts"})
    try:
        result = await collection.aggregate(pipeline, maxTimeMS=max_time_ms).to_list(length=1)
    except PyMongoError as exc:
        raise PreflightTimeout("aggregate", index.collection, index.name) from exc
    return result[0]["conflicts"] if result else 0


async def _has_array_values(collection, field: str, max_time_ms: int) -> bool:
    """Bounded existence check only — returns a bool, never a document/value."""
    try:
        found = await collection.count_documents({field: {"$type": "array"}}, limit=1, maxTimeMS=max_time_ms)
    except PyMongoError as exc:
        raise PreflightTimeout("multikey_detection", collection.name if hasattr(collection, "name") else None) from exc
    return found > 0


async def run_preflight(mongo_url: str, db_name: str, client_factory: Callable = AsyncIOMotorClient, max_time_ms: int | None = None) -> dict:
    max_time_ms = DEFAULT_MAX_TIME_MS if max_time_ms is None else max(1, min(max_time_ms, MAX_ALLOWED_MAX_TIME_MS))

    for index in expected_indexes():
        reject_unmodeled_collation(index)

    client = client_factory(mongo_url, serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS, connectTimeoutMS=CONNECT_TIMEOUT_MS)
    try:
        db = client[db_name]
        try:
            existing = set(await db.list_collection_names())
        except PyMongoError as exc:
            raise PreflightTimeout("list_collection_names") from exc
        collections = sorted({x.collection for x in expected_indexes()})

        document_counts: dict[str, int] = {}
        size_estimates: dict[str, dict[str, int]] = {}
        for name in collections:
            if name not in existing:
                document_counts[name] = 0
                size_estimates[name] = {"storage_size_bytes": 0, "avg_obj_size_bytes": 0}
                continue
            try:
                document_counts[name] = await db[name].estimated_document_count(maxTimeMS=max_time_ms)
                stats = await db.command("collStats", name, maxTimeMS=max_time_ms)
            except PyMongoError as exc:
                raise PreflightTimeout("collection_stats", name) from exc
            size_estimates[name] = {
                "storage_size_bytes": int(stats.get("storageSize", 0)),
                "avg_obj_size_bytes": int(stats.get("avgObjSize", 0)),
            }

        unique_conflicts = []
        multikey_unsupported = []
        for index in expected_indexes():
            if not index.unique or index.collection not in existing:
                continue
            collection = db[index.collection]
            array_field_found = False
            for field, _ in index.fields:
                if await _has_array_values(collection, field, max_time_ms):
                    array_field_found = True
                    break
            if array_field_found:
                multikey_unsupported.append({"collection": index.collection, "name": index.name, "status": "UNSUPPORTED_MULTKEY_PREFLIGHT"})
                continue
            n = await _conflict_group_count(collection, index, max_time_ms)
            if n:
                unique_conflicts.append({"collection": index.collection, "name": index.name, "conflict_groups": n})

        if multikey_unsupported:
            status = "UNSUPPORTED_MULTKEY_PREFLIGHT"
        elif unique_conflicts:
            status = "BLOCKED"
        else:
            status = "READY"

        return {
            "status": status,
            "classification": classify_manifest(),
            "required_immediately": {k: {"collection": c, "name": n} for k, (c, n) in REQUIRED_IMMEDIATELY.items()},
            "staged_migration_order": staged_migration_order(),
            "document_counts": document_counts,
            "size_estimates": size_estimates,
            "unique_conflicts": unique_conflicts,
            "multikey_unsupported": multikey_unsupported,
            "max_time_ms_used": max_time_ms,
        }
    except PreflightTimeout as exc:
        return {
            "status": "INCOMPLETE_UNSAFE",
            "reason": "operation_timeout",
            "stage": exc.stage,
            "collection": exc.collection,
            "index_name": exc.index_name,
            "max_time_ms_used": max_time_ms,
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
    max_time_ms = resolve_max_time_ms(env)
    try:
        report = asyncio.run(run_preflight(mongo_url, db_name, client_factory, max_time_ms=max_time_ms))
    except ValueError as exc:
        print(json.dumps({"status": "UNMODELED_COLLATION", "reason": str(exc)}))
        return 2
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason_code": exc.__class__.__name__}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
