# Security Patch 0D — Tenant-Scoped Append-Only Audit Ledger

## Model and append-only policy

`audit_events` is a dedicated insert-only collection. Each event contains a server-generated `aud_*` ID, shared server-generated `op_*` operation ID, canonical database-backed `tenant_id`, UTC timestamp, schema version, phase/outcome, controlled action/entity/source values, affected entity ID, database-backed actor fields, correlation ID, changed-field names, bounded allowlisted state summaries, stable reason code/message, and SHA-256 integrity hash. No client route creates, updates, or deletes an audit event. Application code exposes only insertion and read helpers.

## Audit-first envelope and failure semantics

Authenticated mutations append `started` before the primary write. Failure to insert `started` blocks the write with a sanitized 503. Expected write conflicts append `rejected`; unexpected primary failures append `failed`. A successful write appends `succeeded`. If that terminal append fails, the normal primary success response is retained, a fixed warning is logged, and the started-only operation remains visible for reconciliation. MongoDB transactions are not required.

Public signup is audited after its tenant/user exist, using that new server-created identity. Because signup cannot record a valid tenant-scoped event before tenant creation, its audit is best-effort and never contains password material.

## Tenant and actor authority

Tenant and actor fields are derived exclusively from the freshly database-loaded authenticated user. Audit reads always add that canonical tenant predicate; owner/admin have no cross-tenant override. `GET /api/audit-events` and `GET /api/audit-events/incomplete` are owner/admin-only, bounded, deterministic, read-only, and reject unknown filters. No global endpoint exists.

## Integrity scope

The hexadecimal hash is SHA-256 over stable, sorted, compact JSON of every immutable event field except `integrity_hash` and MongoDB `_id`. `verify_integrity` recomputes it. This detects event-content changes; it does **not** prove that a database administrator did not delete a complete event.

## Sensitive-data policy

One sanitizer admits only bounded operational fields. It excludes password/hash, JWT/token, authorization/header/body, secret/key/credential, environment/database values, raw request bodies, document contents, unbounded notes, stack traces, and URL query credentials. Strings are capped at 256 characters, summaries at 32 fields, changed-field lists at 32 names. Document evidence is limited to safe identifiers/type/filename/load metadata.

## Activity compatibility

`GET /api/activity` retains its existing array and keys (`id`, `tenant_id`, `load_id`, `action`, `old_status`, `new_status`, `updated_by`, `timestamp`, `notes`). New successful load audit events are mapped to this shape and merged with tenant-scoped legacy activity, newest first. New operations do not write legacy activity. Legacy records are neither deleted nor backfilled by this patch.

## Reconciliation

The internal read-only reconciliation helper returns tenant-scoped started events older than a configurable threshold that lack a succeeded/rejected/failed event. The owner/admin endpoint is bounded to 100. It never repairs data. A future worker may reconcile incomplete operations.

## Seed and migration

Force seed appends one tenant-scoped seed operation before destructive tenant data changes. It never deletes `audit_events`, `activity`, users, or tenants. Patch 0C migration is unchanged and must not be run automatically. Historical activity remains legacy data; audit history must never be assigned, rewritten, or backfilled by the tenant migration. Any future migration must use an explicit reviewed policy and preserve original evidence.

## Deployment prerequisites and indexes

Before deployment, provision collection validation/permissions so the application identity can insert and read but cannot update/delete audit events, then create reviewed indexes (not applied by this patch): unique `id`; `(tenant_id, occurred_at)`; `(tenant_id, operation_id)`; `(tenant_id, entity_type, entity_id)`; `(tenant_id, action, occurred_at)`; `(tenant_id, outcome, occurred_at)`; and optionally `integrity_hash`. Monitor the fixed terminal-warning log and reconcile started-only operations.
