# Controlled Staging Certification

Status: PREPARATION COMPLETE; ENVIRONMENT INPUT REQUIRED  
Certification timestamp: 2026-08-10 (America/New_York)  
Repository/branch: `metaphora-control-tower-v1` / `staging-certification`  
Base/HEAD at pre-flight: `247660d` — Phase 2G: Pilot Security & Golden Freight Flow Certification (#18)  
Environment identity: NOT PROVIDED (no deployment or database connection attempted)

## Evidence register

| Gate | Result | Evidence / required action |
|---|---|---|
| Pre-flight | PASS | Correct branch and HEAD; starting tree clean; origin identified. |
| Code Pilot Candidate | PASS | Phase 2G baseline retained; post-change approved offline regression passed 910 tests and frontend production build compiled successfully. |
| Existing harness review | DEFECT CORRECTED | Old harness dropped a name-guarded DB before proving it empty/owned and covered only one partial index. It now requires explicit disposable confirmation, refuses nonempty DBs, derives its plan from the manifest, and owns cleanup. |
| Index manifest dry review | PASS | Authoritative manifest only; machine-readable plan available with `verify_real_mongo.py --plan --json`. Duplicate identity/direction validation is offline tested. |
| Real-Mongo safety guard | PASS (code); NOT EXECUTED (environment) | No fallback; test/staging APP_ENV only; disposable name; explicit no-customer/disposable confirmation; initial emptiness required. |
| Disposable Mongo | UNAVAILABLE | `METAPHORA_TEST_MONGO_URI`, DB, and confirmation were absent by presence-only inspection. REAL MONGO CERTIFICATION REQUIRES EXPLICIT DISPOSABLE URI. |
| Index application/unique/partial semantics | NOT EXECUTED | Requires guarded disposable Mongo. Harness covers email policy, Action Center recurrence, execution history, operation null/missing key semantics, invoice/package authority. |
| Mongo topology/sessions/transactions | UNKNOWN / NOT EXECUTED | Harness uses server `hello`; transaction commit/abort runs only for session-capable replica-set/sharded topology. |
| Pilot UoW mode | DURABLE_SAGA | Phase 2B default is explicit durable saga; observed transaction support will not auto-enable transactional mode. |
| Real concurrency | NOT EXECUTED | Harness covers Action Center identity, atomic outbox lease/stale-finalize, operation idempotency, invoice claim, active execution authority. No exactly-once external-side-effect claim. |
| Cleanup | NOT APPLICABLE | No DB was accessed. Executed harness may drop only an initially empty DB it owns. |
| Staging configuration/JWT/CORS/seed | DEFINED / UNVERIFIED | Contract is in `STAGING_DEPLOYMENT_CHECKLIST.md`; actual staging values/behavior not available. Secret values must never enter this report. |
| Document storage | LOCAL, SINGLE-HOST PILOT ONLY | Acceptable only with a restricted persistent volume and single instance. Restart/redeploy durability is UNKNOWN and mandatory. |
| Deployment availability | UNAVAILABLE | No authorized staging connection and no Railway/Docker/Procfile/Nixpacks deployment definition found. STAGING DEPLOYMENT REQUIRES OPERATOR ACTION. |
| Backend/frontend health, auth, CORS behavior | NOT EXECUTED | Requires deployed isolated staging. |
| Restart/redeploy persistence | NOT EXECUTED | Must retain Mongo state and document bytes/hashes; failure blocks readiness. |
| Synthetic staging Golden Flow and RC/POD | NOT EXECUTED | Operator procedure defined; no customer data and no external submission. |
| Cross-tenant document test | NOT EXECUTED | Procedure includes authorized hash/header checks and foreign-tenant denial. |
| Production integrity | NOT EXECUTED AGAINST STAGING | Read-only scan required; critical finding blocks. |
| Backup/document backup/restore/audit | NOT EXECUTED | Separate disposable restore target and validation procedure defined. |
| RPO/RTO | UNKNOWN | Targets: 24 hours / 8 hours. Durations and data-loss window unmeasured. |
| Performance smoke/observability | NOT EXECUTED | Bounded endpoints and request-ID test defined. |
| Pilot readiness evaluator | BLOCKED | Evaluator now requires actual deployment, Mongo, concurrency, durability, recovery, integrity, and behavioral evidence. |
| Python syntax | PASS | `compileall -q app scripts tests` using an isolated bytecode cache. |
| Backend regression | PASS | 910 passed, 6 deprecation warnings. |
| Frontend build | PASS | Optimized Create React App production build compiled successfully. |
| GitHub CI | NOT EXECUTED FOR LOCAL CHANGES | Phase 2G base was green; local uncommitted changes have no CI run. |
| Customer Pilot Ready | NOT EVALUATED | Explicitly outside this workstream. |

## Blockers and limitations

P0: none discovered in offline preparation. Any inability to prove the external target is non-production/customer-free becomes P0 and stops execution.

P1: disposable Mongo/index/topology/session/transaction/concurrency evidence; isolated deployment; strong staging JWT; behavioral CORS/auth; persistent document durability; backend/frontend health; deployed synthetic Golden Flow; document isolation; backup/restore/audit verification; staging integrity scan; readiness result; post-change CI confirmation.

P2: local document storage remains a single-host operational constraint; transaction mode remains durable saga even if topology supports transactions; smoke timings are not benchmark/load certification.

## Access and scope attestations

- Production database accessed: NO.
- Customer data accessed: NO.
- External deployment performed: NO.
- External provider submission performed: NO.
- AI/agent/product feature added: NO.
- Phase 2H work performed: NO.
- Commit/push performed: NO.

## Exact next operator input

1. Place the explicitly disposable Mongo URI, disposable database name, and confirmation in the operator environment/secret manager (not chat): `METAPHORA_TEST_MONGO_URI`, `METAPHORA_TEST_MONGO_DB`, `METAPHORA_TEST_MONGO_DISPOSABLE_CONFIRMED=true`, with `APP_ENV=staging`.
2. Identify an already-authorized, provably isolated staging backend service and frontend host/origin.
3. Confirm a single-instance persistent document volume and its backup mechanism; otherwise document workflows keep staging blocked.

Current verdict: **CONTROLLED STAGING NOT READY**. Mandatory environment gates remain unexecuted.
