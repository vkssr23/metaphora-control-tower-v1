"""Dry-run-first legacy single-company tenant backfill.

Importing this module performs no work. Execution requires both the exact
confirmation text and a separate single-company consolidation acknowledgement.
"""
import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from app.tenant import new_tenant_id, validate_tenant_id

OPERATIONAL_COLLECTIONS = ("trucks", "drivers", "loads", "documents", "invoices", "activity", "assumptions")
CONFIRMATION = "BACKFILL_SINGLE_TENANT"
CONSOLIDATION_WARNING = (
    "WARNING: every record missing tenant_id in the reported collections will "
    "be assigned to one tenant. Continue only when all unmigrated data belongs "
    "to one legitimate company/workspace; unrelated companies require a custom migration plan."
)


@dataclass(frozen=True)
class MigrationPlan:
    owner: dict
    tenant_id: str | None
    tenant_name: str
    create_tenant: bool
    counts: dict[str, int]


def missing_tenant_filter() -> dict:
    return {"$or": [{"tenant_id": {"$exists": False}}, {"tenant_id": None}, {"tenant_id": ""}]}


def normalize_owner_email(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or "@" not in normalized:
        raise RuntimeError("A valid owner email is required")
    return normalized


def build_plan(database, owner_email: str, tenant_name: str, requested_tenant_id: str | None) -> MigrationPlan:
    """Validate all database preconditions without writing anything."""
    if requested_tenant_id is not None:
        validate_tenant_id(requested_tenant_id)
    normalized = normalize_owner_email(owner_email)
    owners = list(database.users.find({"email": normalized}))
    if len(owners) == 0:
        raise RuntimeError("Owner lookup returned no match")
    if len(owners) > 1:
        raise RuntimeError("Owner lookup is ambiguous")
    owner = owners[0]
    if owner.get("role") != "owner":
        raise RuntimeError("Selected user does not have owner role")

    owner_tenant = owner.get("tenant_id") or None
    if owner_tenant is not None:
        validate_tenant_id(owner_tenant)
    target_id = requested_tenant_id or owner_tenant
    if owner_tenant and target_id != owner_tenant:
        raise RuntimeError("Owner belongs to a conflicting tenant")

    existing = database.tenants.find_one({"id": target_id}) if target_id else None
    if owner_tenant and not existing:
        raise RuntimeError("Owner tenant record is missing")
    if existing and existing.get("name") != tenant_name:
        raise RuntimeError("Target tenant metadata does not match")

    counts = {"users": database.users.count_documents(missing_tenant_filter())}
    counts.update({name: database[name].count_documents(missing_tenant_filter()) for name in OPERATIONAL_COLLECTIONS})
    return MigrationPlan(owner, target_id, tenant_name, not bool(existing), counts)


def apply_plan(database, plan: MigrationPlan, id_factory: Callable[[], str] | None = None) -> tuple[str, dict[str, int]]:
    """Apply a fully validated plan; existing tenant ownership is never overwritten."""
    tenant_id = validate_tenant_id(plan.tenant_id or (id_factory or new_tenant_id)())
    if plan.create_tenant:
        now = datetime.now(timezone.utc).isoformat()
        database.tenants.insert_one({"id": tenant_id, "name": plan.tenant_name, "status": "active", "created_at": now, "updated_at": now})
    database.users.update_many(missing_tenant_filter(), {"$set": {"tenant_id": tenant_id}})
    for name in OPERATIONAL_COLLECTIONS:
        database[name].update_many(missing_tenant_filter(), {"$set": {"tenant_id": tenant_id}})
    return tenant_id, plan.counts


def run(database, *, owner_email: str, tenant_name: str, requested_tenant_id: str | None,
        execute: bool, confirmation: str, acknowledge_consolidation: bool,
        output: Callable[[str], None] = print, id_factory: Callable[[], str] | None = None) -> int:
    if execute and confirmation != CONFIRMATION:
        output("Execution denied: exact confirmation is required")
        return 2
    if execute and not acknowledge_consolidation:
        output("Execution denied: single-tenant consolidation acknowledgement is required")
        return 2
    try:
        plan = build_plan(database, owner_email, tenant_name, requested_tenant_id)
        output(CONSOLIDATION_WARNING)
        output("Legacy records by collection:")
        for name, count in plan.counts.items():
            output(f"  {name}: {count}")
        if not execute:
            output("Dry run only; zero writes performed")
            return 0
        apply_plan(database, plan, id_factory)
        output("Backfill completed")
        return 0
    except Exception:
        output("Migration failed safely")
        return 3


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--acknowledge-single-tenant-consolidation", action="store_true")
    return parser.parse_args(argv)


def main(argv=None, *, client_factory=None, environ=None) -> int:
    args = parse_args(argv)
    if args.tenant_id is not None:
        try:
            validate_tenant_id(args.tenant_id)
        except ValueError:
            print("Invalid tenant ID", file=sys.stderr)
            return 2
    if args.execute and (args.confirm != CONFIRMATION or not args.acknowledge_single_tenant_consolidation):
        print("Execution denied: both confirmation controls are required", file=sys.stderr)
        return 2
    environment = os.environ if environ is None else environ
    mongo_url, db_name = environment.get("MONGO_URL"), environment.get("DB_NAME")
    if not mongo_url or not db_name:
        print("Database configuration is required", file=sys.stderr)
        return 2
    try:
        if client_factory is None:
            from pymongo import MongoClient
            client_factory = MongoClient
        client = client_factory(mongo_url)
        try:
            return run(client[db_name], owner_email=args.owner_email, tenant_name=args.tenant_name,
                       requested_tenant_id=args.tenant_id, execute=args.execute,
                       confirmation=args.confirm,
                       acknowledge_consolidation=args.acknowledge_single_tenant_consolidation)
        finally:
            client.close()
    except Exception:
        print("Migration failed safely", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
