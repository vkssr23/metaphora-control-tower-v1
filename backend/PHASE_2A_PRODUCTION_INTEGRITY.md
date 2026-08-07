# Phase 2A Production Integrity Foundation

## Purpose and status

Phase 2A provides observational, fail-safe tooling for evaluating pilot readiness. It does **not** certify production readiness, connect to a database, apply indexes, repair records, perform a backup or restore, deploy, or validate real MongoDB behavior.

## Architecture

- `app/infrastructure/index_manifest.py` is the single immutable application index manifest. Definitions have stable names, ordered keys, uniqueness, exact lifecycle partial filters, purpose, and P0/P1/P2 priority. Normal startup never creates indexes.
- `app/production_integrity.py` scans bounded plain record collections. Detection is separate from data acquisition and output formatting. Findings use controlled severity and stable codes; only bounded IDs are included, never record bodies or secret fields.
- `scripts/production_integrity_report.py` reads an explicitly supplied JSON export and optional observed-index JSON. It has no Mongo adapter or mutation mode. Critical blockers return exit code 2.
- `app/observability.py` supplies bounded request IDs, `X-Request-ID`, duration/status/error classification, and structured standard-library logs. Headers, bodies, credentials, tokens, passwords, secrets, and document contents are excluded or redacted.

## Integrity and severity model

`critical` means tenant isolation, uniqueness, financial authority, or production simulation can make pilot operation unsafe. `high` is a broken authoritative relationship or lifecycle disagreement. `medium` is migration/concurrency readiness debt. `low` and `info` are bounded advisory levels.

Checks cover missing/malformed/nonexistent tenant membership, cross-tenant parents, orphans, unique-index collisions (using the manifest's exact partial filters), missing lifecycle versions, unsupported and incomplete documents, mock storage, delivery/execution disagreement, and invoice/readiness/package/load authority disagreement. Unknown critical data produces a finding rather than a silent pass. Historical terminal workflow records are excluded from active uniqueness filters.

Execution-session uniqueness is derived directly from the Phase 1F transition graph. `pending_start`, `active`, `paused`, `exception`, `delivery_arrived`, and `delivery_confirmed` are current/nonterminal and participate in the unique partial index; only `completed` and `cancelled` are terminal history and excluded.

P0 unique keys with a missing or explicit-null component are critical rollout blockers. The scanner conservatively groups missing and null as the same indexed-null bucket for collision preflight and never calls such fixtures safe. This is deliberately conservative and is not a substitute for disposable real-Mongo validation. Stored user email must equal the application's trimmed lowercase canonical form; canonical duplicates are reported even when differently cased physical strings would not collide in Mongo's plain `email` index.

The migration summary counts tenant backfill, duplicates, orphans, unsupported documents, version/lifecycle gaps, legacy invoice authority, active-case duplicates, and all index collisions. Phase 2A never backfills, merges, deletes, or changes authority.

## Invoice authority

The scanner reports invoices without Phase 1G readiness authority, readiness marked invoiced without its exact `invoice_id`, missing package links, orphan package/readiness/invoice links, conflicting unique authority, and legacy load/invoice status disagreement. Modern authority requires reciprocal stored relationships among readiness `invoice_id`/`invoice_package_id`, invoice `readiness_case_id`/`package_id`, and package `readiness_case_id`/`invoice_id`, with matching tenant and load. A same-load legacy invoice never satisfies modern linkage. Coexisting legacy and modern invoices are an explicit Phase 2C authority conflict. Stored financial-basis fingerprints are compared only when present and comparable; missing values are reported as not comparable and are never synthesized.

## Simulation inventory and environment readiness

The central inventory records the actual source route/feature, default reachability, real runtime gate (if any), classification, and pilot impact for routing, weather, road/traffic, Samsara, fuel/truck-stop, random dashboard, mock document storage, and seed behavior. Simulated endpoints and `mock://` support that are unconditionally reachable remain critical pilot blockers in production-like environments regardless of invented or unused environment flags. The seed route alone uses its existing runtime gate. The evaluator reports only `configured`, `missing`, or `unsafe`; it checks explicit `APP_ENV`, JWT-secret strength without emitting its value, Mongo configuration presence, explicit CORS, seed policy, frontend backend URL, and actual simulation reachability. It never calls a provider.

Delivered loads are classified conservatively. A load is execution-managed when a same-tenant Phase 1F session exists or a readiness basis carries an execution-session reference. Missing delivery evidence is then a modern integrity finding. A Delivered load with no Phase 1F evidence is reported as legacy/unverifiable migration debt, not falsely labeled modern workflow corruption and not silently passed.

Report severity totals cover all detected findings. `returned_findings` is bounded by the requested limit, and `truncated` is true only when a finding was actually omitted.

Production readiness combines environment results, supplied integrity results, and observed-versus-expected index metadata into `PASS`, `WARN`, or `FAIL`. Missing index evidence is `UNKNOWN`, never pass. `production_certified` always remains false in this foundation.

## Safe operator workflow

From `backend`, run only against an approved, bounded, sanitized export:

```text
python -m scripts.production_integrity_report --environment staging --input approved-export.json --observed-indexes approved-index-metadata.json --json
```

Omitting `--input` scans an empty fixture; omitting observed indexes yields `UNKNOWN`. The command is read-only and contains no repair/apply path. Do not point Phase 2A at production, staging, Railway, Emergent, or another remote database.

## Backup and restore validation runbook — NOT EXECUTED BY PHASE 2A

1. Obtain authorization from the designated production data owner; only that owner may authorize a destructive migration.
2. Create the required pre-migration backup using the approved platform procedure and capture its immutable identifier, time, scope, encryption, and retention policy.
3. Restore into an isolated, access-controlled environment—not over staging or production.
4. Verify per-tenant and per-collection record counts against captured source counts without exposing record contents.
5. Run the integrity report on the isolated restore and retain the report identifier.
6. Compare observed indexes with the manifest.
7. Run application authentication, tenant isolation, lifecycle, document, and invoice smoke tests.
8. Record pass/fail evidence and make an explicit proceed/rollback decision.
9. Confirm retention and deletion handling for both backup and isolated restore.

No backup or restore was performed or validated by Phase 2A.

## Future index rollout runbook — NOT EXECUTED BY PHASE 2A

1. Back up.
2. Validate restore.
3. Run the integrity scan.
4. Resolve critical duplicates and orphans through separately reviewed migration work.
5. Rerun the report.
6. Test intentional index creation in disposable staging.
7. Run application lifecycle smoke tests.
8. Schedule production rollout and approvals.
9. Create indexes intentionally; never through application startup.
10. Compare observed indexes with the manifest.
11. Monitor conflicts and errors.
12. Retain rollback and reconciliation evidence.

## Health semantics

`/api/health/live` says only that the process is alive. `/api/health/ready` evaluates configuration and explicitly returns `production_integrity: not_certified`; it does not query or certify data. The existing root status remains a process/application response, not a data-integrity assertion.

## Explicit exclusions and remaining dependencies

Phase 2A does not implement Phase 2B transactions/outbox, the Mutation Impact Planner, Phase 2C authority cleanup, Phase 2E storage, external integrations, migrations, repair commands, index application, deployment, or frontend redesign.

Relationship checks resolve populated fields as current/live references. They do not generally prove whether a frozen historical snapshot was intentionally retained after its former live parent was removed. Optional absent historical references are not treated as proof of integrity. Any workflow needing historical-reference semantics requires a later domain-specific migration review.

A later disposable real-Mongo suite is still P0 and must validate partial unique indexes, collision behavior, transactions/topology, write concerns, sessions, and concurrency. Fake/plain-record tests do not prove those properties. A single real full-lifecycle test was not forced into Phase 2A because existing fixtures are route-phase-specific; it remains a Phase 2G P0 item covering Load → RC → Passport → Party → Eligibility → Pickup Release → Pickup Confirmed → Execution → Delivery → POD → Invoice Readiness → ready-for-submission.
