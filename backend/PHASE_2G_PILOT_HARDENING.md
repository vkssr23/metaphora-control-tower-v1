# Phase 2G — Pilot Security, Golden Freight Flow, and Hardening

## Objective and architecture

Phase 2G asks whether the existing carrier Freight Execution OS may enter controlled staging. It adds certification—not new product authority—through a Golden Freight Flow spine, adversarial regressions, secret-free readiness evaluator, guarded disposable Mongo harness, PR CI, threat model, ADRs, and operational governance. `server.py` and product routes are unchanged.

## Golden Freight Flow V1

The canonical lifecycle is tenant/user capabilities → driver/truck/load → immutable RC bytes and SHA-256 → explicit extraction/acceptance → Passport → Party Verification → Eligibility → version-bound pickup authorization/consumption → execution → source exception → Action Center projection and role-controlled acknowledgement → source resolution → delivery → immutable POD → explicit Invoice Readiness/finance approval → Phase 2B idempotent package/invoice/outbox operation → `ready_for_submission`, externally `not_submitted`.

**GOLDEN FREIGHT FLOW: PASS — coherent lifecycle test executed.** `tests/test_phase_2g_golden_flow.py` uses one TestClient, authenticated operations/safety/finance/owner actors, one shared fake database, and isolated temporary Phase 2E storage. Real HTTP routes perform fleet/load creation, multipart documents, RC extraction/acceptance, Passport checkpoints/transitions, party review/clearance, eligibility review/finalization, pickup release/consumption, execution/stop departure/exception/delivery/completion, Action Center refresh/acknowledgement, and Invoice Readiness/approval/Phase 2B invoice creation and replay. Only tenant/master membership records are fixture seeds. No internal authority shortcut or direct final-state write is used.

Upload never accepts an RC, claims authenticity, approves POD finance authority, or submits an invoice externally. Action acknowledgement never mutates source state. The same tenant, load, documents, workflow records, audit collection, operation, package, invoice, and outbox persist through the complete test.

## Security attack matrix

| Surface | Certification |
|---|---|
| Cross-tenant load/document/action | Existing tenant isolation, document download, and Action Center privacy route tests |
| Role escalation | Phase 2G owner/category matrix plus Phase 2F route matrix |
| Stale RC/pickup/assignment | Phase 1B/1E and Phase 2C impact tests |
| Document abuse | Phase 2E traversal, CRLF, size, MIME/signature, legacy URL, tenant hash/download and partial-failure tests |
| Finance/duplicate invoice | Phase 1G/2B/2C authority, amount, idempotency, race and reconciliation tests |
| Partial failure | Audit, document, invoice/outbox and Action Center completeness/CAS suites |

No internet penetration test, provider call, SSRF fetch, production access, AI, or deployment occurs.

## Real Mongo, indexes, transactions, concurrency

`scripts/verify_real_mongo.py` only accepts `METAPHORA_TEST_MONGO_URI` plus a guarded disposable `METAPHORA_TEST_MONGO_DB`; it never falls back to `MONGO_URI` and rejects production `APP_ENV`. It applies the final Phase 2A manifest only there, compares index metadata, probes abort/commit transactions, and verifies Action Center partial-unique behavior. The supplied environment had no approved test URI: **REAL-MONGO HARNESS IMPLEMENTED — NOT EXECUTED**. Consequently index, transaction, and real concurrency status are **NOT VERIFIED** and P1 before customer traffic. No normal/production DB or index was accessed/applied.

## Pilot readiness and configuration

`app/pilot_readiness.py` separately evaluates environment, JWT, explicit CORS, seed exposure, document backend, offline regression, Golden Flow, adversarial suite, real Mongo, indexes, transactions, and restore evidence. Unknown mandatory evidence blocks readiness. Output contains codes and next steps, never secret values or URIs. Local document storage is `LOCAL_PILOT_ONLY`, not a false blocker when durable restricted single-host storage and backup are accepted.

## CI quality gates

PR CI performs backend syntax, the offline suite excluding only approved preview/network modules, explicit Phase 2G discovery, and the existing frontend production build. It has no deployment, provider, production DB, or secret-printing step. The first remote backend CI run exposed that the legacy demo `emergentintegrations==0.2.0` package was not portable to a clean public Python environment. Phase 2G.2 removed that optional legacy AI dependency from the core manifest and made the legacy endpoint controlled-unavailable when its runtime or key is absent. The first remote frontend CI run then exposed a pre-existing `react-hooks/exhaustive-deps` warning in the Load Execution Samsara effect; CI correctly treated the warning as an error. Phase 2G.3 corrected the effect's dependency semantics using a truck-ID-bound callback rather than weakening the CI gate. Remote CI run #2 passed the frontend, backend dependency installation, and backend syntax steps, but backend test collection failed because TestClient's `httpx` dependency was not explicit and bare `pytest` did not preserve the backend source root for top-level `app` and `scripts` imports. Phase 2G.4 pins the locally certified `httpx` version and invokes pytest through `python -m pytest` from `backend`, without path hacks or added exclusions. **LOCAL CI-EQUIVALENT FRONTEND BUILD: PASS. LOCAL CI-EQUIVALENT BACKEND: PASS. REMOTE GITHUB BACKEND CI: PENDING RE-RUN.** These corrections add no AI or telematics capability certification; GitHub Actions must rerun to prove the corrected clean install and builds remotely.

## Governance and operations

The repository now includes the grounded threat model; seven ADRs; technical debt and direct dependency/license inventory; engineering constitution; pilot performance targets; SLO/incident foundation; and backup/restore runbook. Licenses unavailable from manifests are honestly `UNKNOWN / REVIEW REQUIRED`. No SOC 2/ISO/PCI/HIPAA claim is made. Log redaction and `nosniff` document behavior remain covered by existing tests. Pilot data classes are Public, Internal, Confidential, and Highly Sensitive.

## Defect register

No new material product defect was found during implementation. Phase 2G initially used no unsupported transition bypass. Open operational risks are listed in `docs/TECHNICAL_DEBT.md`.

## How to certify a staging build

1. Configure an isolated staging/test environment and verify secrets/CORS/seeding.
2. Provision disposable/staging Mongo; run the real-Mongo harness and apply/verify reviewed indexes.
3. Run offline regression and Golden Freight Flow/security suites.
4. Run `python scripts/pilot_readiness_report.py --json` with evidence flags.
5. Execute the documented backup/restore drill and validate audit/documents/authority.
6. Only then designate a controlled staging pilot candidate. No deployment is part of Phase 2G.

## Certification levels and verdict policy

**A. CODE PILOT CANDIDATE** requires offline regression, coherent Golden Flow, adversarial security, and readiness/configuration logic. This level passes in the current offline environment.

**B. CONTROLLED STAGING READY** additionally requires real-Mongo/index/topology verification, executed backup/restore, and staging secrets/CORS/storage. This level is blocked.

**C. CUSTOMER PILOT READY** additionally requires controlled-staging acceptance, defect closure, and operational readiness. It is not yet evaluated.

Phase 2H may introduce first real external integrations. Phase 3 may introduce an Agent Tool & Approval Plane. Neither exists here. Performance numbers and SLOs are targets, not measured compliance.

Current environment: real-Mongo/index/transaction behavior and backup/restore are unverified, so the truthful verdict is **NOT PILOT READY — BLOCKERS REMAIN** until those P1 staging gates execute successfully.
