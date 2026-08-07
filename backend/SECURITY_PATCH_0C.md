# Security Patch 0C: Tenant Isolation

Operational records in `trucks`, `drivers`, `loads`, `documents`, `invoices`,
`activity`, and `assumptions` are owned by the server-controlled `tenant_id`.
Users receive tenant membership from their database record; JWT, body, query,
URL, and client headers are never tenant authority. Normalized email lookup is
the sole intentional global authentication exception.

Public signup creates a new active tenant, tenant defaults, and a viewer user.
It cannot join an existing tenant. Owners and admins remain tenant-level roles.
Assumption initialization during signup is best-effort after the tenant and
user writes. A sanitized fixed error is logged on failure; the tenant-scoped
`GET /assumptions` path safely creates only that user's missing defaults later.

## Samsara simulation contract

The frontend sends the assigned `truck_id`, never a synthetic vehicle value.
The backend resolves that ID with the authenticated `tenant_id`, then uses the
truck's stored `samsara_id` when present. The existing telematics list may send
that actual stored ID, which is also resolved by exact tenant-scoped lookup.
A truck without one receives a clearly
marked simulated response tied to the resolved truck. Missing and foreign truck
IDs return the same 404 response. No external Samsara request is performed.

## Legacy migration runbook

### Single-company prerequisite

The utility assigns every record missing `tenant_id` to one tenant. It is safe
only when all unmigrated records belong to the same legitimate organization.
Do not use it for databases containing unrelated carriers, customers, acquired
businesses, or workspaces. Operators must manually review counts and ownership
boundaries. Multi-company data requires stopping and creating a custom plan;
the utility deliberately performs no automatic company inference.

Owner candidates, role, existing tenant membership, target tenant metadata,
and all counts are validated before the first write. A conflicting owner tenant
aborts execution without creating or updating anything.

### Canonical tenant IDs and fail-closed membership

Tenant IDs use exactly `^ten_[0-9a-f]{32}$`: the `ten_` prefix followed by 32
lowercase hexadecimal characters. Whitespace is forbidden. Invalid supplied
IDs are never stripped, case-folded, or otherwise normalized; they fail before
database-client construction and before every write.

The application has no automatic, default, or fallback tenant. Missing or
malformed database user membership fails operational access closed with the
stable 403 response. Ordinary requests never assign legacy users or records.
The explicit migration must be completed and verified before deployment.

1. Back up the database and verify the backup.
2. Confirm the database represents one legacy company.
3. Run the utility without `--execute` using an explicit tenant name and owner email.
4. Review every count, ownership boundary, and cross-record relationship.
5. Validate the selected owner and target tenant.
6. Execute only with `--execute --confirm BACKFILL_SINGLE_TENANT` and
   `--acknowledge-single-tenant-consolidation`.
7. Verify every user and operational record has the intended `tenant_id`.
8. Apply and verify the documented tenant-aware indexes.
9. Run tenant-isolation smoke tests.
10. Deploy tenant-enforced code only after validation succeeds.
11. Roll back the application deployment if validation fails; the utility never
    deletes data or overwrites an existing `tenant_id`.

### Partial-failure behavior

Migration collection updates are not transactional. A later collection can
fail after earlier missing records were updated, and the script then returns a
non-zero status. A verified database backup is mandatory before execution.
After any failure, rerun the dry-run and manually verify every count and tenant
boundary. Existing `tenant_id` values are never overwritten, so controlled
reruns are idempotent. Production deployment must not proceed until migration
verification passes completely.

### Rollback and restoration

Application rollback, database restoration, and a controlled idempotent rerun
are separate actions:

1. Stop application deployment or traffic.
2. Preserve migration command output and dry-run counts.
3. Determine whether a partial database write occurred.
4. Restore the mandatory pre-migration backup or snapshot when ownership cannot
   be validated safely.
5. Do not broadly remove tenant fields without a reviewed rollback plan.
6. Re-run the dry-run after restoration.
7. Verify user and per-collection counts and ownership boundaries.
8. Re-apply migration only after correcting the original failure.
9. Verify tenant-aware indexes.
10. Deploy tenant-enforced code only after successful migration verification.

Rolling back application code does not restore partially changed data. A
controlled rerun is appropriate only after ownership is validated; missing-only
updates and immutable existing tenant IDs make that rerun idempotent.

## Recommended indexes (do not apply automatically)

- Unique global normalized user email (preserve current global uniqueness)
- Unique tenant `id`; unique `(tenant_id, id)` for operational collections
- Unique `(tenant_id, truck_number)` and appropriate tenant-scoped driver IDs
- Tenant-scoped load/rate-con and invoice identifiers
- `(tenant_id, created_at)` and `(tenant_id, timestamp)` for list/activity reads
- Unique `(tenant_id, id)` on assumptions, yielding one `id=default` per tenant

No index or migration is applied on startup or in tests.

Patch 0D note: this migration must not assign tenant IDs to, rewrite, or backfill
`audit_events`. Legacy `activity` remains readable under its existing tenant scope;
historical conversion requires a separate reviewed evidence-preservation plan.
