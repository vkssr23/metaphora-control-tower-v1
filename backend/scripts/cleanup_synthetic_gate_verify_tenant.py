"""One-purpose cleanup for the exact synthetic gate-verification tenant/user
created during production behavior verification on 2026-08-26 (Sprint 2E
merge check). Fixed IDs only — no arbitrary tenant argument, and this
script deletes nothing else, ever.

Dry-run by default. --execute additionally requires --confirm with the
exact CONFIRMATION phrase. Precheck must pass in full before any delete is
attempted, in either mode; a mismatch on any single check aborts the whole
run with no partial action.

Never prints email, password hash, token, credential, document payload, or
environment values — only booleans, counts, and ids already known to the
caller (TENANT_ID/USER_ID are constants in this file, not derived from
output).
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

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConfigurationError, InvalidOperation, PyMongoError

from app.production_integrity import TENANT_SCOPED

TENANT_ID = "ten_fdcbe506cd24489eb1159aa242a11159"
USER_ID = "UDB5D9D4F"
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


async def precheck(db) -> dict:
    """Read-only. Never returns the email itself — only a marker boolean."""
    tenant = await db.tenants.find_one({"id": TENANT_ID}, {"_id": 0, "id": 1, "created_at": 1}, max_time_ms=MAX_TIME_MS)
    users = await db.users.find({"tenant_id": TENANT_ID}, {"_id": 0, "id": 1, "created_at": 1, "email": 1}, max_time_ms=MAX_TIME_MS).to_list(length=10)

    counts = {}
    for collection in sorted(TENANT_SCOPED):
        # users is checked separately above (exact identity, not just a
        # count); audit_events is inventoried and preserved below, not a
        # "business record" that must be zero.
        if collection in ("users", "audit_events"):
            continue
        counts[collection] = await db[collection].count_documents({"tenant_id": TENANT_ID}, maxTimeMS=MAX_TIME_MS)

    audit_events = await db.audit_events.find({"tenant_id": TENANT_ID}, {"_id": 0, "id": 1}, max_time_ms=MAX_TIME_MS).to_list(length=50)

    matching_user = next((u for u in users if u.get("id") == USER_ID), None) if len(users) == 1 else None
    email = matching_user.get("email") if matching_user else None
    email_marker_ok = isinstance(email, str) and EMAIL_DOMAIN_MARKER in email

    checks = {
        "tenant_found": tenant is not None,
        "tenant_id_matches": bool(tenant and tenant.get("id") == TENANT_ID),
        "tenant_created_in_window": _in_window((tenant or {}).get("created_at")),
        "exactly_one_user_for_tenant": len(users) == 1,
        "user_id_matches": matching_user is not None,
        "user_created_in_window": _in_window((matching_user or {}).get("created_at")),
        "synthetic_email_marker_present": email_marker_ok,
        "zero_business_records": all(v == 0 for v in counts.values()),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "related_record_counts": counts,
        "audit_event_count": len(audit_events),
        "audit_event_ids": [a.get("id") for a in audit_events],
    }


async def _both_already_absent(db) -> bool:
    tenant = await db.tenants.find_one({"id": TENANT_ID}, {"_id": 1}, max_time_ms=MAX_TIME_MS)
    user = await db.users.find_one({"id": USER_ID}, {"_id": 1}, max_time_ms=MAX_TIME_MS)
    return tenant is None and user is None


async def _transactions_supported(client) -> bool:
    try:
        hello = await client.admin.command("hello")
    except PyMongoError:
        return False
    topology_ok = bool(hello.get("setName")) or hello.get("msg") == "isdbgrid"
    sessions_ok = hello.get("logicalSessionTimeoutMinutes") is not None
    return topology_ok and sessions_ok


async def execute(db, client) -> dict:
    if await _both_already_absent(db):
        return {"status": "ALREADY_CLEANED_UP"}

    pre = await precheck(db)
    if not pre["ok"]:
        return {"status": "ABORT_PRECHECK_FAILED", "checks": pre["checks"]}

    if not await _transactions_supported(client):
        return {"status": "ABORT_NO_TRANSACTION_SUPPORT"}

    session = await client.start_session()
    deleted = {"user": 0, "tenant": 0}
    try:
        async with session.start_transaction():
            du = await db.users.delete_one({"id": USER_ID, "tenant_id": TENANT_ID}, session=session)
            dt = await db.tenants.delete_one({"id": TENANT_ID}, session=session)
            if du.deleted_count != 1 or dt.deleted_count != 1:
                raise RuntimeError("delete_count_mismatch")
            deleted["user"], deleted["tenant"] = du.deleted_count, dt.deleted_count
    except (PyMongoError, ConfigurationError, InvalidOperation, RuntimeError) as exc:
        return {"status": "ABORT_TRANSACTION_FAILED", "reason_code": exc.__class__.__name__}
    finally:
        await session.end_session()

    tenant_absent = (await db.tenants.find_one({"id": TENANT_ID}, {"_id": 1}, max_time_ms=MAX_TIME_MS)) is None
    user_absent = (await db.users.find_one({"id": USER_ID}, {"_id": 1}, max_time_ms=MAX_TIME_MS)) is None
    audit_preserved = await db.audit_events.count_documents({"tenant_id": TENANT_ID}, maxTimeMS=MAX_TIME_MS)
    verified = deleted["user"] == 1 and deleted["tenant"] == 1 and tenant_absent and user_absent
    return {
        "status": "DELETED" if verified else "ABORT_VERIFY_FAILED",
        "deleted_user_count": deleted["user"],
        "deleted_tenant_count": deleted["tenant"],
        "tenant_absent": tenant_absent,
        "user_absent": user_absent,
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
