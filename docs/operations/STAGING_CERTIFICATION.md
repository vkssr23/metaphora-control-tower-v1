# Controlled Staging Certification

Status: REAL-MONGO CERTIFIED; CONTROLLED STAGING NOT READY
Certification evidence recorded: 2026-08-12 (America/New_York)
Repository/branch: `metaphora-control-tower-v1` / `staging-certification`  
Evidence-recording pre-flight HEAD: `d823256` — safe real-Mongo certification diagnostics
Diagnostic correction pre-flight HEAD: `866ddd7` — controlled staging certification preparation
Base/HEAD at pre-flight: `247660d` — Phase 2G: Pilot Security & Golden Freight Flow Certification (#18)  
Environment identity: Railway `staging-certification`, temporary `mongo-certifier` service, explicit disposable certification database only

## Operator-observed real environment evidence

The following was directly observed by the operator from the successful Railway run. Codex did not access Mongo or Railway and did not rerun the harness.

- Certification **PASS**; database classification `DISPOSABLE_TEST`; MongoDB **8.0.28**, separately confirmed with `db.version()`.
- Index plan **PASS**: all 49 intended manifest indexes created/verified, none missing or mismatched, and no unexpected index material to certification.
- Topology **standalone**; sessions supported **true**; transactions **UNSUPPORTED_TOPOLOGY**.
- `PILOT_UOW_MODE` **durable_saga**. Transactional atomicity is not claimed.
- Unique/partial semantics **PASS**, covering Action Center active rejection/resolved recurrence, canonical-email policy, nonterminal execution/terminal history, invoice/package authority, operation identity, and missing/null optional idempotency behavior.
- Real concurrency **PASS**: one winner each for Action Center, execution, invoice, operation, and outbox lease. Stale outbox finalization was rejected; valid-winner finalization succeeded.
- Cleanup `OWNED_DISPOSABLE_DATABASE_DROPPED`; production accessed **false**; customer data accessed **false**; URI included **false**.
- GitHub Auto Deploy is disabled on the temporary `mongo-certifier` service.

### Environment-certification history

The first attempt failed safely during index creation with `14031` / `OutOfDiskSpace`: the Railway Trial volume was 0.5 GB and MongoDB 8's index-build disk-space safety threshold applied. After moving to Hobby and live-resizing `mongodb-volume` to 5.00 GB, the rerun passed. This resolved infrastructure condition is not an open product defect and does not establish an index-manifest defect.

## Offline/code verification

Offline evidence is separate. Harness guards, bounded diagnostics, cleanup ownership, and manifest-plan tests passed in the approved 913-test backend suite. The existing frontend build is unchanged. No real-environment claim derives from offline tests alone.

## Evidence register

| Gate | Result | Evidence / required action |
|---|---|---|
| Pre-flight | PASS | Correct branch, clean starting tree, and `d823256` present. |
| Code Pilot Candidate | PASS | Phase 2G baseline retained; safe-diagnostics approved offline regression passed 913 tests. Existing frontend build remains unchanged. |
| Existing harness review | DEFECT CORRECTED | Old harness dropped a name-guarded DB before proving it empty/owned and covered only one partial index. It now requires explicit disposable confirmation, refuses nonempty DBs, derives its plan from the manifest, and owns cleanup. |
| Index manifest dry review | PASS | Authoritative manifest only; machine-readable plan available with `verify_real_mongo.py --plan --json`. Duplicate identity/direction validation is offline tested. |
| Real-Mongo safety guard | PASS | Operator run used the explicit disposable certification database; no production fallback or customer data. |
| Disposable real Mongo | PASS — CLOSED | Successful Railway run; `DISPOSABLE_TEST`; MongoDB 8.0.28. |
| Index manifest / P0 indexes | PASS — CLOSED | Plan passed; 49 intended indexes verified; none missing or mismatched. Manifest unchanged. |
| Unique and partial semantics | PASS — CLOSED | Representative protected behavior matched current manifest policy. |
| Mongo topology | STANDALONE — CLOSED | Actual topology characterized. |
| Sessions | SUPPORTED — CLOSED | Actual server capability known. |
| Transactions | UNSUPPORTED_TOPOLOGY — CLOSED AS CHARACTERIZED | Not a transaction pass; no transactional atomicity claim. |
| Pilot UoW mode | DURABLE_SAGA — CLOSED | Explicit mode compatible with the standalone topology. |
| Real concurrency | PASS — CLOSED | Exactly one authority/lease winner per bounded probe; stale outbox finalization rejected. |
| Cleanup | PASS — CLOSED | `OWNED_DISPOSABLE_DATABASE_DROPPED`. |
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
| Pilot readiness evaluator | BLOCKED | Mongo evidence is complete; deployment, durability, recovery, integrity, and behavioral evidence remain mandatory. |
| Python syntax | PASS | `compileall -q app scripts tests` using an isolated bytecode cache. |
| Backend regression | PASS | 913 passed, 6 deprecation warnings after safe diagnostic instrumentation. |
| Frontend build | PASS | Optimized Create React App production build compiled successfully. |
| GitHub CI | NOT EXECUTED FOR LOCAL CHANGES | Phase 2G base was green; local uncommitted changes have no CI run. |
| Customer Pilot Ready | NOT EVALUATED | Explicitly outside this workstream. |

## Blockers and limitations

P0: none discovered in offline preparation. Any inability to prove the external target is non-production/customer-free becomes P0 and stops execution.

Closed Mongo-related P1 gates: disposable real Mongo, intended indexes, topology, sessions, transaction capability characterization, explicit UoW mode, representative concurrency, and cleanup.

Open P1 gates: isolated backend deployment; staging JWT; exact CORS configuration and behavioral test; safe seed behavior; persistent document storage; restart/redeploy document persistence; frontend deployment; deployed health/auth verification; synthetic staging Golden Freight Flow; production-integrity scan; Mongo/data and document backups; restore drill; restored hash/audit verification; final pilot-readiness evaluation; and post-change CI confirmation.

P2: local document storage remains a single-host operational constraint; transaction mode remains durable saga even if topology supports transactions; smoke timings are not benchmark/load certification.

## Access and scope attestations

- Production database accessed: NO (operator-observed report and this documentation update).
- Customer data accessed: NO.
- External deployment performed: NO.
- External provider submission performed: NO.
- AI/agent/product feature added: NO.
- Phase 2H work performed: NO.
- Commit/push performed: NO.

## Exact next operator input

1. Identify an already-authorized, isolated Metaphora staging backend service and frontend host/origin; neither has been deployed.
2. Configure staging JWT, exact CORS, safe seed behavior, and a persistent document volume without tracking secrets.
3. Execute deployment, behavioral/E2E, persistence, integrity, backup/restore, and final readiness gates.

Current verdict: **CONTROLLED STAGING NOT READY**. Mongo certification is complete, but mandatory application deployment and recovery gates remain. **CUSTOMER PILOT READY: NOT EVALUATED.**
