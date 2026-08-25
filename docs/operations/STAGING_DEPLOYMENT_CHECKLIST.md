# Controlled Staging Deployment Checklist

Status: OPERATOR_EXECUTION_REQUIRED. Scope: `staging-certification` at commit `247660d` or its reviewed descendant. This is not a production deployment and does not authorize customer traffic.

## 1. Pre-flight and environment identity

- Record project, service, environment, region, commit SHA, timestamp, and operator without secret values.
- Prove the target is isolated staging/test, has no production/customer traffic, and cannot resolve to production Mongo or storage. If this cannot be proven, stop.
- Confirm GitHub backend/frontend CI is green. Do not make external Mongo a required PR job.
- Current repository contains no Railway, Docker, Procfile, Nixpacks, or other deployment definition. Backend start command must therefore be set explicitly (for example, from `backend`: `uvicorn server:app --host 0.0.0.0 --port $PORT`). Frontend is a static Create React App build (`yarn install --frozen-lockfile`, `yarn build`); select and record an operator-approved static host.

## 2. Secret-safe staging contract

Set through the deployment secret manager, never a tracked file or report:

- `APP_ENV=staging`.
- `JWT_SECRET`: unique to staging, at least 32 characters, not a default/development/CI value. Record only that validation passed.
- `CORS_ORIGINS`: the exact HTTPS staging frontend origin and only any separately justified operator origin. No wildcard or broad regex.
- Application Mongo: `MONGO_URL` and `DB_NAME`, pointing only to the isolated staging database.
- Certification Mongo: `METAPHORA_TEST_MONGO_URI`, `METAPHORA_TEST_MONGO_DB`, and `METAPHORA_TEST_MONGO_DISPOSABLE_CONFIRMED=true` only for a separate, empty, operator-confirmed disposable database. Never reuse application Mongo.
- `ALLOW_SEED_ENDPOINT=false`.
- `DOCUMENT_STORAGE_BACKEND=local`, `DOCUMENT_STORAGE_ROOT=<restricted persistent-volume mount>`, and an approved `DOCUMENT_MAX_UPLOAD_BYTES` (1 KiB–100 MiB; default 15 MiB).
- Frontend backend URL required by the current build configuration; record its variable name after inspecting the selected host/build pipeline.
- Logging level/destination must preserve request IDs, redact credentials, JWTs, Mongo URIs, storage paths, and request bodies.
- Simulation policy: simulated/mock document URLs and legacy demo/AI endpoints must not be used by certification. No external provider is required.
- `PILOT_UOW_MODE=durable_saga` as the declared Phase 2B mode. Transaction support is probed but does not auto-enable transactional UoW.

## 3. Mongo plan, indexes, and concurrency

1. Render the secret-free authoritative plan: `cd backend && python scripts/verify_real_mongo.py --plan --json`.
2. Review collection, ordered fields, uniqueness, partial filter, priority, purpose, duplicate names, and supported directions. The only source is `app/infrastructure/index_manifest.py`.
3. Confirm the certification database is empty and disposable; set its URI in the operator environment, not chat or shell history where avoidable.
4. Run `python scripts/verify_real_mongo.py --json`. The harness refuses nonempty targets, applies without dropping conflicting indexes, verifies metadata and representative partial/unique semantics, identifies topology/session/transaction capability, performs bounded races, then drops only the initially empty database it owned.
5. Preserve secret-free output. Any missing/mismatched/conflicting P0 index or failed authority race blocks staging. Do not drop/recreate an application index automatically.

## 4. Document storage and deployment

- Controlled staging is supported only as a single backend instance with a restricted persistent volume. Ephemeral or multi-instance local storage blocks document workflows.
- Before traffic, verify the volume is mounted at `DOCUMENT_STORAGE_ROOT`, is writable only by the service identity, and is included in backup.
- Deploy backend and frontend to explicitly staging services. Configure liveness/readiness checks using the existing public health route; confirm output contains no URI, secret, or filesystem path.
- Verify backend liveness, frontend load, login, unauthenticated rejection, mis-role mutation denial, and valid-user success.
- From the real frontend origin, verify CORS succeeds. From an unrelated origin, verify it is rejected.
- Verify no startup seed occurs and a restart creates no duplicate seed records.

## 5. Synthetic staging Golden Freight Flow

Use a uniquely prefixed synthetic tenant/load and synthetic PDF/image bytes. Do not use customer data.

1. Use the current gated bootstrap/signup mechanism for a pilot owner; do not enable `/api/seed`.
2. Login; create driver, truck, and load. Upload a synthetic RC, create structured RC evidence, accept it, then complete Passport, Party Verification, Eligibility, Pickup Release, pickup confirmation, and Execution.
3. Create a manual exception; verify Action Center creation. If a second role is available, verify wrong-role acknowledgement denial, then correct acknowledgement. Resolve the source exception and verify Action Center resolution.
4. Complete delivery; upload synthetic POD; complete execution; verify Invoice Readiness and an invoice/package in `ready_for_submission`.
5. Do not invoke external submission. Record `NO_EXTERNAL_SUBMISSION_VERIFIED=true` only after checking outbox/provider state.
6. Download RC/POD as the authorized tenant; verify SHA-256, bounded safe `Content-Disposition`, `X-Content-Type-Options: nosniff`, and absence of filesystem paths. A foreign tenant must receive denial.
7. Run the read-only production-integrity scanner against the synthetic staging dataset; no automatic repair. Any critical finding blocks readiness.

## 6. Restart, redeploy, performance, and observability

- Restart the staging backend. Verify database state, RC/POD bytes and hashes, frontend reconnection, reconstructed readiness/Action Center state, and no seed duplicates.
- If safe, redeploy the same known-good commit. Repeat persistence checks. Missing document bytes is P1 and blocks staging.
- Record bounded timings for health, authenticated read, load list/detail, Action Center, document download, and invoice-readiness read; compare with `docs/PERFORMANCE_BUDGETS.md`. This is a smoke check, not a load test.
- Verify request IDs are emitted and returned, expected errors are bounded/redacted, and one failed request can be correlated in logs without sensitive data.

## 7. Backup and restore drill

- Create an encrypted Mongo backup and a consistent document-volume backup; capture audit events. Do not back up secret values into the evidence report.
- Restore into a separate, empty, disposable restore database and separate document root. Never overwrite staging in the drill.
- Point a temporary verification service/read-only tooling at the restore target. Verify tenant/load counts, RC/POD object presence and SHA-256, invoice/package/readiness state, Action Center, outbox/reconciliation consistency, audit presence/integrity, indexes, and cross-tenant denial.
- Record backup, restore, and verification durations; observed data-loss window; calculated RPO observation; and RTO observation. Targets are RPO 24 hours and RTO 8 hours.
- Delete only drill resources whose disposable identity and ownership are proven.

## 8. Readiness and rollback

- Supply only actually verified evidence flags to `cd backend && python scripts/pilot_readiness_report.py --json`. Never force an unexecuted flag green.
- Roll back application code only to the recorded previous known-good compatible commit. Preserve database and document volume.
- Index rollback is forward corrective: never destructively drop/recreate indexes without a reviewed compatibility reason and backup. Do not roll back customer/staging data to match code.
- If schema/index compatibility is uncertain, stop traffic and restore the known-good application while retaining data for investigation.
- `CUSTOMER PILOT READY` remains `NOT EVALUATED` after controlled staging certification.

Operator inputs required now: an explicitly disposable Mongo URI/database supplied through environment secret management; identity of isolated staging backend/frontend services; and confirmation of a single-instance persistent document volume (or an explicit decision that document staging remains blocked).
