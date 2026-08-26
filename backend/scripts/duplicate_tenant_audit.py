"""Bounded, read-only audit of the single conflicting metaphora_org_id
tenant group already found by index_migration_preflight.py
(unique_conflicts: [{"collection": "tenants", "name":
"uq_tenants_metaphora_org_id", "conflict_groups": 1}]).

Locates that one group via aggregation, then reports only: a one-way
fingerprint of the org id (never the id itself), both tenant ids,
creation timestamp/status, a smoke-tenant name-pattern heuristic (boolean
only — the tenant name itself is fetched, used, and discarded, never
returned), user counts, per-tenant related-record counts across every
tenant-scoped collection, and SSO-linkage presence booleans. No document
payload, email, token, or credential is ever read or printed.

No create_index/insert/update/delete/drop/merge call anywhere in this
module — it cannot act on its own findings.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError

from app.production_integrity import TENANT_SCOPED
from scripts.index_migration_preflight import DEFAULT_MAX_TIME_MS, MAX_ALLOWED_MAX_TIME_MS, resolve_max_time_ms

# Heuristic only — no codified smoke-tenant id/flag exists in this schema.
# Verify org_ids are small sequential integers, so a SHA-256 fingerprint
# gives correlation-safety (two audits agree it's "the same org") but is
# NOT resistant to an attacker who brute-forces the small id space; it is
# not a confidentiality boundary, only an output-hygiene one.
SMOKE_TENANT_NAME_MARKERS = ("smoke", "phase2g-cert", "test-cert")
MAX_TENANTS_IN_GROUP = 10  # bounded report size; a larger group is reported truncated, not printed in full


class AuditTimeout(Exception):
    def __init__(self, stage: str, tenant_id: str | None = None, collection: str | None = None):
        self.stage, self.tenant_id, self.collection = stage, tenant_id, collection
        super().__init__(stage)


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _find_conflicting_group(db, max_time_ms: int) -> dict | None:
    pipeline = [
        {"$match": {"metaphora_org_id": {"$exists": True}}},
        {"$group": {"_id": "$metaphora_org_id", "ids": {"$push": "$id"}, "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": 1},
    ]
    try:
        result = await db.tenants.aggregate(pipeline, maxTimeMS=max_time_ms).to_list(length=1)
    except PyMongoError as exc:
        raise AuditTimeout("find_conflict_group") from exc
    return result[0] if result else None


async def _tenant_report(db, tenant_id: str, max_time_ms: int) -> dict:
    try:
        # find()/find_one() build a pymongo Cursor, whose __init__ takes an
        # explicit, non-**kwargs parameter list — the Python-side name is
        # max_time_ms (snake_case). Unlike aggregate()/count_documents()/
        # command()/estimated_document_count(), which end in a permissive
        # **kwargs merged straight into the wire command (so the BSON-style
        # camelCase maxTimeMS works there), Cursor.__init__ has no such
        # catch-all — passing maxTimeMS here raises
        # "TypeError: unexpected keyword argument 'maxTimeMS'".
        doc = await db.tenants.find_one(
            {"id": tenant_id},
            {"_id": 0, "id": 1, "status": 1, "created_at": 1, "name": 1, "metaphora_org_id": 1},
            max_time_ms=max_time_ms,
        )
    except PyMongoError as exc:
        raise AuditTimeout("tenant_lookup", tenant_id) from exc
    doc = doc or {}
    name = str(doc.get("name", ""))
    is_smoke = any(marker in name.lower() for marker in SMOKE_TENANT_NAME_MARKERS)

    related_counts: dict[str, int] = {}
    for collection in sorted(TENANT_SCOPED):
        try:
            related_counts[collection] = await db[collection].count_documents({"tenant_id": tenant_id}, maxTimeMS=max_time_ms)
        except PyMongoError as exc:
            raise AuditTimeout("related_count", tenant_id, collection) from exc

    return {
        "tenant_id": tenant_id,
        "created_at": doc.get("created_at"),
        "status": doc.get("status"),
        "is_known_smoke_tenant": is_smoke,
        "has_metaphora_org_id": bool(doc.get("metaphora_org_id")),
        "user_count": related_counts.get("users", 0),
        "related_record_counts": related_counts,
    }


async def run_audit(mongo_url: str, db_name: str, client_factory: Callable = AsyncIOMotorClient, max_time_ms: int | None = None) -> dict:
    max_time_ms = DEFAULT_MAX_TIME_MS if max_time_ms is None else max(1, min(max_time_ms, MAX_ALLOWED_MAX_TIME_MS))
    client = client_factory(mongo_url, serverSelectionTimeoutMS=DEFAULT_MAX_TIME_MS, connectTimeoutMS=DEFAULT_MAX_TIME_MS)
    try:
        db = client[db_name]
        try:
            group = await _find_conflicting_group(db, max_time_ms)
            if group is None:
                return {"status": "NO_CONFLICT_FOUND", "max_time_ms_used": max_time_ms}

            tenant_ids = list(group["ids"])
            truncated = len(tenant_ids) > MAX_TENANTS_IN_GROUP
            tenant_ids = tenant_ids[:MAX_TENANTS_IN_GROUP]

            tenants = [await _tenant_report(db, tid, max_time_ms) for tid in tenant_ids]
        except AuditTimeout as exc:
            return {
                "status": "INCOMPLETE_UNSAFE", "reason": "operation_timeout",
                "stage": exc.stage, "tenant_id": exc.tenant_id, "collection": exc.collection,
                "max_time_ms_used": max_time_ms,
            }

        return {
            "status": "CONFLICT_AUDITED",
            "org_id_fingerprint_sha256": fingerprint(str(group["_id"])),
            "conflict_group_size": group["n"],
            "reported_tenants_truncated": truncated,
            "tenants": tenants,
            "reassignment_fields": {
                "per_tenant_scoped_collection_field": "tenant_id",
                "tenant_scoped_collections": sorted(TENANT_SCOPED),
                "sso_link_field_on_tenants": "metaphora_org_id",
            },
            "max_time_ms_used": max_time_ms,
        }
    finally:
        client.close()


def _safe_diagnostic(exc: BaseException) -> dict:
    """Script filename, function, and source line number only — never the
    exception message, locals, values, documents, URI, or a full traceback."""
    frames = traceback.extract_tb(exc.__traceback__)
    own_frames = [f for f in frames if Path(f.filename).name == Path(__file__).name]
    frame = own_frames[-1] if own_frames else (frames[-1] if frames else None)
    if frame is None:
        return {"file": None, "function": None, "line": None}
    return {"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}


def main(argv: list[str] | None = None, environ: dict | None = None, client_factory: Callable = AsyncIOMotorClient) -> int:
    env = os.environ if environ is None else environ
    mongo_url, db_name = env.get("MONGO_URL"), env.get("DB_NAME")
    if not mongo_url or not db_name:
        print(json.dumps({"status": "ERROR", "reason": "MONGO_URL and DB_NAME must both be set"}))
        return 2
    max_time_ms = resolve_max_time_ms(env)
    try:
        report = asyncio.run(run_audit(mongo_url, db_name, client_factory, max_time_ms=max_time_ms))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason_code": exc.__class__.__name__, "diagnostic": _safe_diagnostic(exc)}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "CONFLICT_AUDITED" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
