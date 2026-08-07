# Phase 1A — Verified Load Passport Core

The load passport is a tenant-owned operational trust record for one canonical load. It stores bounded snapshots and human administrative decisions; it does not replace loads, drivers, trucks, documents, assumptions, or the append-only audit ledger.

## Model and lifecycle

`load_passports` holds server-generated identity, tenant and actor fields, an immutable `load_id`, optimistic `version`, lifecycle timestamps, bounded load/party/rate-confirmation/profitability/assignment snapshots, required checkpoints, evidence document IDs, blockers, and an embedded pickup authorization. One active record is allowed per tenant/load. The strict lifecycle is `draft → review_pending → approved|blocked`, `blocked → review_pending`, `approved → pickup_authorized|revoked`, `pickup_authorized → revoked`, and `revoked → review_pending`. Conditional tenant/id/status/version predicates return 409 on lost updates.

## Checkpoints and roles

Required types are load details, rate confirmation, broker identity, shipper identity, profitability, driver eligibility, truck eligibility, trailer eligibility, appointment feasibility, and pickup instructions. Decisions are pending/pass/fail/waived/expired. Operations/dispatcher owns load, rate, party, appointment, and instruction reviews; safety/compliance owns driver/truck/trailer eligibility; finance owns profitability; owner/admin owns all types, waivers, approval, authorization, and revocation. Phase 1A client decisions are manual; `system` is server-only and `future_integration` is reserved.

## Readiness and human policy

The pure readiness evaluator checks required blocking decisions, the current tenant load, assignment consistency, material snapshot drift, profitability, blockers, lifecycle status, pre-pickup load stages, current approval version, and duplicate active authorization. Approval and pickup authorization are never inferred and require an owner/admin action. Pickup authorization is an evidence record, not a bearer credential; it binds one passport version and current driver, truck, trailer, pickup data, and checkpoint state through canonical-JSON SHA-256. Duplicate active issuance is rejected.

## Snapshots, changes, and evidence

Creation allowlists load, broker/shipper identity, latest rate-confirmation metadata, deterministic profitability using the tenant's existing assumptions/formula, and current tenant driver/truck assignment. Document contents and credential-bearing URLs are never copied. Evidence IDs must resolve to the same tenant and load. Assignment snapshots do not claim eligibility. Material load, rate, lane, party, assignment, equipment, commodity/weight, or rate-confirmation changes invalidate approval, revoke active authorization, increment version, reset affected checkpoints, and add `material_change_requires_reapproval`.

Every mutation uses Patch 0D's audit-first envelope with controlled events for creation, update, checkpoint review, profitability refresh, submission, approval/block/revocation, material invalidation, and pickup issue/revocation. Tenant and actors are always database-controlled; cross-tenant records appear as 404.

## Limitations and future integration

Phase 1A uses internal administrative checkpoints. It does **not** claim real FMCSA, insurance, identity, broker, shipper, HOS, ELD, telematics, OCR, fraud, credential, authority, or document verification. External evidence integrations belong to later phases.

Recommended production indexes (not applied here): unique `(tenant_id,id)`, unique `(tenant_id,load_id)`, `(tenant_id,status,updated_at)`, and `(tenant_id,pickup_authorization.id)`.

## Cross-collection material-change safety

When approval or pickup authorization is active, passport invalidation occurs before a material canonical load write or rate-confirmation document insert. The conditional invalidation predicate binds the authenticated tenant, passport ID, observed status, observed version, and active authorization state where applicable. Losing that race returns 409 and prevents the canonical write.

If invalidation succeeds but the later canonical write fails, the passport remains conservatively `review_pending`, its approval stays cleared, its authorization stays revoked, affected checkpoints remain pending, and `material_change_requires_reapproval` remains active. Approval is never automatically restored. A post-write snapshot synchronization failure likewise cannot reactivate approval or authorization.

This deliberate fail-safe policy can require unnecessary human re-review, but that is preferable to retaining an unsafe stale pickup authorization. A future MongoDB transaction or transactional outbox should make the cross-collection operation fully atomic without unsafe compensation.
