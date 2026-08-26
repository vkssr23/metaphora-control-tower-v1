"""One-purpose cleanup for the exact synthetic gate-verification tenant,
user, and its auto-created default assumptions document, created during
production behavior verification on 2026-08-26 (Sprint 2E merge check).
Fixed IDs only — no arbitrary tenant argument, and this script deletes
nothing else, ever.

Dry-run by default. --execute additionally requires --confirm with the
exact CONFIRMATION phrase. Precheck must pass in full before any delete is
attempted, in either mode; a mismatch on any single check aborts the whole
run with no partial action.

Never prints email, password hash, token, credential, document payload
(including the assumptions document's field values), or environment
values — only booleans, counts, and ids already known to the caller
(TENANT_ID/USER_ID/ASSUMPTIONS_DOC_ID are constants in this file, not
derived from output).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConfigurationError, InvalidOperation, PyMongoError

from app.constants import DEFAULT_ASSUMPTIONS
from app.production_integrity import TENANT_SCOPED

TENANT_ID = "ten_fdcbe506cd24489eb1159aa242a11159"
USER_ID = "UDB5D9D4F"
# tenant_document(user, DEFAULT_ASSUMPTIONS) in auth_routes.py's signup()
# writes DEFAULT_ASSUMPTIONS verbatim plus tenant_id — "id" is always the
# literal string "default" (one per tenant, enforced by the
# uq_assumptions_tenant_id_id unique index), not a generated per-document
# id. No application-level created_at exists on this document, so the
# creation-time check below uses Mongo's own _id ObjectId timestamp instead.
ASSUMPTIONS_DOC_ID = DEFAULT_ASSUMPTIONS["id"]
EMAIL_DOMAIN_MARKER = "sprint2e-gate-check.dev"
# Tight window around the actual verification signup (2026-08-26T00:45:38Z),
# defense-in-depth beyond the id match.
CREATED_WINDOW_START = datetime(2026, 8, 26, 0, 45, 0, tzinfo=timezone.utc)
CREATED_WINDOW_END = datetime(2026, 8, 26, 0, 46, 0, tzinfo=timezone.utc)
CONFIRMATION = "DELETE_SYNTHETIC_GATE_VERIFY_TENANT"
MAX_TIME_MS = 4000


def _in_window(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return CREATED_WINDOW_START <= ts <= CREATED_WINDOW_END


def _object_id_in_window(oid) -> bool:
    if not isinstance(oid, ObjectId):
        return False
    return CREATED_WINDOW_START <= oid.generation_time <= CREATED_WINDOW_END


def _assumptions_matches_default_schema(doc: dict) -> bool:
    """Every DEFAULT_ASSUMPTIONS field must be present and unmodified — a
    customized/edited assumptions doc must never be treated as the
    untouched signup default. Never returns or logs the field values."""
    return all(doc.get(k) == v for k, v in DEFAULT_ASSUMPTIONS.items())


async def precheck(db) -> dict:
    """Read-only. Never returns the email or assumptions field values —
    only marker booleans."""
    tenant = await db.tenants.find_one({"id": TENANT_ID}, {"_id": 0, "id": 1, "created_at": 1}, max_time_ms=MAX_TIME_MS)
    users = await db.users.find({"tenant_id": TENANT_ID}, {"_id": 0, "id": 1, "created_at": 1, "email": 1}, max_time_ms=MAX_TIME_MS).to_list(length=10)
    assumptions = await db.assumptions.find({"tenant_id": TENANT_ID}, max_time_ms=MAX_TIME_MS).to_list(length=10)

    counts = {}
    for collection in sorted(TENANT_SCOPED):
        # users and assumptions are checked separately (exact identity/
        # schema, not just a count); audit_events is inventoried and
        # preserved below, not a "business record" that must be zero.
        if collection in ("users", "assumptions", "audit_events"):
            continue
        counts[collection] = await db[collection].count_documents({"tenant_id": TENANT_ID}, maxTimeMS=MAX_TIME_MS)

    audit_events = await db.audit_events.find({"tenant_id": TENANT_ID}, {"_id": 0, "id": 1}, max_time_ms=MAX_TIME_MS).to_list(length=50)

    matching_user = next((u for u in users if u.get("id") == USER_ID), None) if len(users) == 1 else None
    email = matching_user.get("email") if matching_user else None
    email_marker_ok = isinstance(email, str) and EMAIL_DOMAIN_MARKER in email

    matching_assumptions = assumptions[0] if len(assumptions) == 1 else None

    checks = {
        "tenant_found": tenant is not None,
        "tenant_id_matches": bool(tenant and tenant.get("id") == TENANT_ID),
        "tenant_created_in_window": _in_window((tenant or {}).get("created_at")),
        "exactly_one_user_for_tenant": len(users) == 1,
        "user_id_matches": matching_user is not None,
        "user_created_in_window": _in_window((matching_user or {}).get("created_at")),
        "synthetic_email_marker_present": email_marker_ok,
        "exactly_one_assumptions_for_tenant": len(assumptions) == 1,
        "assumptions_id_matches": bool(matching_assumptions and matching_assumptions.get("id") == ASSUMPTIONS_DOC_ID),
        "assumptions_matches_default_schema": bool(matching_assumptions and _assumptions_matches_default_schema(matching_assumptions)),
        "assumptions_created_in_window": _object_id_in_window((matching_assumptions or {}).get("_id")),
        "zero_business_records": all(v == 0 for v in counts.values()),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "related_record_counts": counts,
        "audit_event_count": len(audit_events),
        "audit_event_ids": [a.get("id") for a in audit_events],
    }


async def _all_already_absent(db) -> bool:
    tenant = await db.tenants.find_one({"id": TENANT_ID}, {"_id": 1}, max_time_ms=MAX_TIME_MS)
    user = await db.users.find_one({"id": USER_ID}, {"_id": 1}, max_time_ms=MAX_TIME_MS)
    assumptions = await db.assumptions.find_one({"id": ASSUMPTIONS_DOC_ID, "tenant_id": TENANT_ID}, {"_id": 1}, max_time_ms=MAX_TIME_MS)
    return tenant is None and user is None and assumptions is None


async def _transactions_supported(client) -> bool:
    try:
        hello = await client.admin.command("hello")
    except PyMongoError:
        return False
    topology_ok = bool(hello.get("setName")) or hello.get("msg") == "isdbgrid"
    sessions_ok = hello.get("logicalSessionTimeoutMinutes") is not None
    return topology_ok and sessions_ok


async def execute(db, client) -> dict:
    if await _all_already_absent(db):
        return {"status": "ALREADY_CLEANED_UP"}

    pre = await precheck(db)
    if not pre["ok"]:
        return {"status": "ABORT_PRECHECK_FAILED", "checks": pre["checks"]}

    if not await _transactions_supported(client):
        return {"status": "ABORT_NO_TRANSACTION_SUPPORT"}

    session = await client.start_session()
    deleted = {"assumptions": 0, "user": 0, "tenant": 0}
    try:
        async with session.start_transaction():
            da = await db.assumptions.delete_one({"id": ASSUMPTIONS_DOC_ID, "tenant_id": TENANT_ID}, session=session)
            du = await db.users.delete_one({"id": USER_ID, "tenant_id": TENANT_ID}, session=session)
            dt = await db.tenants.delete_one({"id": TENANT_ID}, session=session)
            if da.deleted_count != 1 or du.deleted_count != 1 or dt.deleted_count != 1:
                raise RuntimeError("delete_count_mismatch")
            deleted["assumptions"], deleted["user"], deleted["tenant"] = da.deleted_count, du.deleted_count, dt.deleted_count
    except (PyMongoError, ConfigurationError, InvalidOperation, RuntimeError) as exc:
        return {"status": "ABORT_TRANSACTION_FAILED", "reason_code": exc.__class__.__name__}
    finally:
        await session.end_session()

    tenant_absent = (await db.tenants.find_one({"id": TENANT_ID}, {"_id": 1}, max_time_ms=MAX_TIME_MS)) is None
    user_absent = (await db.users.find_one({"id": USER_ID}, {"_id": 1}, max_time_ms=MAX_TIME_MS)) is None
    assumptions_absent = (await db.assumptions.find_one({"id": ASSUMPTIONS_DOC_ID, "tenant_id": TENANT_ID}, {"_id": 1}, max_time_ms=MAX_TIME_MS)) is None
    audit_preserved = await db.audit_events.count_documents({"tenant_id": TENANT_ID}, maxTimeMS=MAX_TIME_MS)
    verified = (
        deleted["assumptions"] == 1 and deleted["user"] == 1 and deleted["tenant"] == 1
        and tenant_absent and user_absent and assumptions_absent
    )
    return {
        "status": "DELETED" if verified else "ABORT_VERIFY_FAILED",
        "deleted_assumptions_count": deleted["assumptions"],
        "deleted_user_count": deleted["user"],
        "deleted_tenant_count": deleted["tenant"],
        "tenant_absent": tenant_absent,
        "user_absent": user_absent,
        "assumptions_absent": assumptions_absent,
        "audit_events_preserved_count": audit_preserved,
    }


async def run(mongo_url: str, db_name: str, do_execute: bool, client_factory: Callable) -> dict:
    client = client_factory(mongo_url, serverSelectionTimeoutMS=MAX_TIME_MS, connectTimeoutMS=MAX_TIME_MS)
    try:
        db = client[db_name]
        if not do_execute:
            report = await precheck(db)
            return {"mode": "DRY_RUN", **report}
        result = await execute(db, client)
        return {"mode": "EXECUTE", **result}
    finally:
        client.close()


def main(argv: list[str] | None = None, environ: dict | None = None, client_factory: Callable = AsyncIOMotorClient) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default=None)
    # argv=None means "no CLI args" for programmatic/test callers, not
    # "fall back to sys.argv" — only the __main__ entry point passes the
    # real sys.argv[1:] explicitly.
    args = parser.parse_args(argv if argv is not None else [])

    if args.execute and args.confirm != CONFIRMATION:
        print(json.dumps({"status": "ABORT_CONFIRMATION_REQUIRED"}))
        return 2

    env = os.environ if environ is None else environ
    mongo_url, db_name = env.get("MONGO_URL"), env.get("DB_NAME")
    if not mongo_url or not db_name:
        print(json.dumps({"status": "ERROR", "reason": "MONGO_URL and DB_NAME must both be set"}))
        return 2

    try:
        report = asyncio.run(run(mongo_url, db_name, args.execute, client_factory))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason_code": exc.__class__.__name__}))
        return 2

    print(json.dumps(report, sort_keys=True))
    if not args.execute:
        return 0 if report["ok"] else 1
    return 0 if report["status"] in {"DELETED", "ALREADY_CLEANED_UP"} else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
