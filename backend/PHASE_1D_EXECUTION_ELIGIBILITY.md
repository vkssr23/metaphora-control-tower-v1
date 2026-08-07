# Phase 1D — Execution Eligibility

Phase 1D answers whether the currently assigned driver, truck, and bounded trailer/load configuration is internally eligible to proceed toward pickup. It is deterministic, tenant-scoped, audit-first, and human-controlled. Administrative statuses are not external verification.

## Record and lifecycle

`execution_eligibility_cases` is tenant-owned with server-controlled `eec_` ID, tenant, actors, timestamps, snapshots, status, verdict, and version. A case binds immutable `load_id` and `passport_id`; one case is allowed per tenant/load and there is no delete route. The lifecycle is `draft → review_pending → eligible|review_required|blocked`; review/blocked/expired/revoked may return to review, and eligible may expire or be revoked. Draft cannot become eligible directly. Conditional status/version writes return 409 on races.

Verdicts are `pending`, `eligible`, `review_required`, and `blocked`. Fail/expired checks block. Warnings, pending checks, and insufficient data require review. Only owner/admin may waive a check with a bounded reason. Operations owns assignments, appointments, trailer identifiers, pickup readiness, and planning notes; safety/compliance owns driver/truck/compliance/equipment safety checks; owner/admin performs final eligibility. Finance and viewers are read-only.

## Deterministic policies

Driver snapshots include only repository fields: ID/name, operational status, CDL and medical expiries, MVR, Clearinghouse, and employment status. Dates use UTC calendar dates: expired blocks, 0–30 days is `expires_soon`/warning, later is current, and missing is insufficient data. MVR maps Clear/pass, Review/warning, Expired/expired; Clearinghouse maps Clear/pass, Pending/warning, Issue/fail; employment maps Complete/pass, Pending/warning. Available/Assigned/Driving pass operational review; Off Duty/Home Time/Missing Update warn; Inactive fails.

Truck snapshots include ID/unit, VIN/year, operational and maintenance statuses, stored expiry dates, and Samsara ID as an identifier only. Available, Assigned, In Transit, At Pickup, At Delivery, and Idle pass; Maintenance and Out of Service fail. Maintenance Good passes, Warn warns, Bad fails. Stored insurance expiry is evaluated with the same date policy; it is not provider verification.

No trailer master is created. The case stores a bounded manual trailer identifier/type. A trailer identifier is required except for Box Truck and Power Only. Compatibility uses the existing Phase 1B vocabulary. Exact types pass; Reefer and specialized equipment mismatches fail; missing/unknown combinations require review and never silently pass. Weight and commodity checks remain manual/insufficient-data or warning because the repository has no capacity, axle, certification, or commodity-compatibility master data; no DOT/legal-weight conclusion is made.

Pickup/delivery ISO timestamps are compared without routing or traffic data: missing values require review, delivery at/before pickup blocks, and a valid sequence passes. HOS evidence is manual load-specific planning: available hours must cover planned hours. Missing evidence requires review and insufficient hours blocks. It is not ELD/HOS verification.

Where Phase 1C or rate-confirmation workflow records exist, the newest tenant/load record is required to be current: party verification must be cleared and bound to the current passport version; rate extraction must be accepted. The current tenant-owned passport must exist and remain version-bound.

## Finalization, synchronization, and invalidation

Final eligibility re-reads all tenant-owned prerequisites, evaluates on the server, then conditionally updates the passport before conditionally marking the case eligible. The passport update increments its version and passes exactly `driver_eligibility`, `truck_eligibility`, `trailer_eligibility`, and `appointment_feasibility`; unrelated checkpoints remain unchanged. A passport race prevents the case write. A later case race never rolls the passport backward.

Material load fields are driver/truck assignments, equipment, commodity, weight, pickup/delivery timing, miles, and estimated drive hours. Driver compliance/operational changes and truck operational, maintenance, insurance/registration/inspection changes are material. These routes use conservative pre-invalidation: return an eligible case to review, reset affected checkpoints, increment both versions, and revoke active pickup authorization before the upstream mutation. Phase 1B accepted-record supersession and Phase 1C clearance loss use the same ordering; all participating mutation paths preserve audit-start and conditional-write semantics.

### Phase 1D.1 safety integration

Eligible cases are immutable through ordinary update, refresh, evaluate, check, finding, evidence, and HOS routes. They may change only through passport-first block/expire/revoke or the controlled material-change invalidator.

Snapshot refresh is allowed only in draft, review-pending, review-required, and blocked states. The strict empty request causes the server to re-read the tenant-owned load, passport, assigned driver/truck, current Party Verification case, and current Rate Confirmation workflow; rebuild bounded snapshots; regenerate deterministic checks/findings; and increment the guarded case version. Refresh never marks a case eligible.

Generated findings use stable IDs derived from check type. Findings may be resolved only in review-pending or review-required. Operations owns assignment, appointment, trailer, and pickup findings; safety/compliance owns driver, compliance, maintenance, insurance-evidence, and equipment-safety findings. Owner/admin may act across domains and may waive only waivable findings with a bounded reason. Assignment and prerequisite findings cannot be waived. Finding identity/type and resolution actor/time are server-controlled.

The HOS-readiness endpoint accepts bounded manual planning values only: drive/on-duty/cycle hours, required trip hours, whether rest is required before pickup, and notes. It stores no raw ELD data and makes no HOS-compliance claim. Insufficient hours block, rest-required warns, and missing planning requires review. Eligible cases cannot be mutated through this endpoint.

All invalidation entry points use one pure `build_invalidation_plan` policy and one audited applicator. Its tenant/case/passport/status/version predicates, affected checks/checkpoints, reason codes, next versions, and authorization revocation decision are explicit. Driver master-data, truck master-data, load/assignment, passport trailer identifier, accepted/superseded Rate Confirmation, and Party Verification block/expire/revoke paths use it before their canonical writes. Driver invalidation resets driver eligibility; truck invalidation resets truck eligibility; assignment/equipment/trailer/appointment/mileage changes reset their mapped checks and checkpoints; prerequisite loss resets all four execution checkpoints.

An active pickup authorization is preserved as evidence but changed to revoked with server actor/time and a bounded reason whenever execution eligibility becomes stale. Nothing automatically restores eligibility, approval, checkpoints, or authorization.

Final eligibility starts its audit before re-reading and recomputing all prerequisites. It conditionally increments and synchronizes the passport before conditionally marking the case eligible. Block, expire, and revoke use the same passport-first ordering. A passport race prevents the case transition. A case race after passport synchronization leaves the passport conservatively reset and is never compensated backward.

Cross-collection writes remain non-transactional in Phase 1D. The system intentionally prefers conservative invalidation and re-review over retaining stale execution eligibility. If invalidation succeeds and a later canonical driver, truck, load, Rate Confirmation, or Party Verification write fails, the case/checkpoints/authorization remain invalidated for reconciliation.

### Phase 1D.2 fail-closed corrections

Party Verification and an accepted Rate Confirmation are mandatory for final Phase 1D eligibility. Requiredness is fixed server policy and is never inferred from whether an optional record happens to exist. A missing, foreign, non-cleared, stale, blocked, expired, or revoked Party Verification case produces `party_verification_required`. A missing, foreign, non-accepted, rejected, or superseded extraction—or one not bound to the passport’s current rate-confirmation document—produces `accepted_rate_confirmation_required`.

Material invalidation is passport-first. After the parent canonical route starts its audit, the shared helper reads the eligible case and passport, starts its bounded child audit records, conditionally resets and increments the passport, revokes any active pickup authorization, and only then conditionally changes the execution case to review-pending/pending. The canonical mutation runs only after both writes succeed. A passport race changes neither passport nor case and blocks the canonical mutation. A case race after passport reset also blocks the canonical mutation, does not compensate backward, and leaves the passport conservatively reset.

Driver and truck discovery is deterministic and fail-closed. Phase 1D has no background invalidation worker, so the synchronous safety ceiling is 100 affected eligible cases. Discovery requests 101 records before any safety write; if the ceiling is exceeded, the master-data mutation returns 409 without partially invalidating or updating canonical data. Within the ceiling, every affected case is processed in stable update/ID order and all must invalidate before the canonical driver or truck write.

Audit ownership is explicit: the driver, truck, load, passport, Rate Confirmation, document, or Party Verification route owns and starts the parent mutation audit before calling shared invalidation. The shared helper owns bounded execution-invalidation and passport-synchronization child audits. No safety write occurs if a required child audit cannot start. No automatic eligibility, checkpoint, approval, or authorization restoration occurs after any successful safety write.

Every mutation begins a controlled audit event before its primary write. Audit metadata is bounded and excludes raw documents, CDL/medical records, ELD logs, credentials, signed URLs, request bodies, and stack traces. Cross-tenant lookups return 404; tenantless users return 403; lists are bounded and newest-first.

Recommended production indexes (not applied here): `(tenant_id,id)`, unique `(tenant_id,load_id)`, `(tenant_id,status,updated_at)`, `(tenant_id,verdict,updated_at)`, `(tenant_id,driver_snapshot.id,status)`, `(tenant_id,truck_snapshot.id,status)`, and `(tenant_id,passport_id)`.

## Limitations and future integrations

Phase 1D does **not** perform live FMCSA, DMV, CDL, medical-card, Clearinghouse, ELD/HOS, insurance-provider, maintenance-provider, Samsara/telematics, or trailer-registry verification. Future adapters may populate separately identified evidence only after authenticated, tenant-safe integrations are designed. Administrative statuses remain internal administrative/planning evidence.
