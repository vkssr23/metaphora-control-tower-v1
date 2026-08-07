# Phase 1G — Delivery Evidence, POD & Invoice Readiness Core

## Purpose and boundaries

Phase 1G creates a tenant-owned, audit-first finance handoff after delivery. It determines whether internal delivery, current accepted rate-confirmation metadata, required document metadata, reviewed charges, and a deterministic billable calculation support human approval and an invoice marked `ready_for_submission`.

It does not verify document or signature authenticity and does not submit externally. There is no live accounting sync, QuickBooks, factoring, payment status, broker receipt, EDI, email submission, OCR, payment collection, banking, or provider integration.

## Readiness case and lifecycle

`invoice_readiness_cases` uses server IDs (`irc_…`), server tenant/actor/time fields, immutable load binding, optimistic `version`, and no delete route. One non-invoiced case is active per tenant/load. Lifecycle states are `draft`, `review_pending`, `review_required`, `ready`, `approved`, `blocked`, `reopened`, and `invoiced`; verdicts are `pending`, `ready`, `review_required`, and `blocked`. General payloads cannot set status, verdict, snapshots, totals, approvals, invoice IDs, or package data.

Submission enters review; evaluation alone may produce ready or blocked; owner/admin approval is a distinct reread-and-recalculate operation; approved is distinct from invoiced. Refresh returns a mutable case to draft/pending and never approves. Approved/invoiced cases reject ordinary refresh.

## Prerequisites and snapshots

Evaluation fails closed unless the same-tenant canonical load is `Delivered`, a current Phase 1F session exists in `delivery_confirmed` execution state or `completed` status, POD metadata is present, the newest Phase 1B extraction is accepted and not superseded, an explicit base charge exists, charges and deductions are resolved, currencies agree, and no unresolved blocking exception exists.

The delivery snapshot is bounded to load/session identity and version, state/status, internal delivered time/reference, custody, stage, and assignment IDs. It never copies events, GPS, ELD, credentials, or raw content. The document snapshot includes only ID, controlled type, bounded filename/upload metadata, and an explicit presence-only/not-authenticity-verified marker.

## Documents and POD

The canonical document vocabulary is reused: `rate_con`, `bol`, `pod`, `lumper`, `scale`, `invoice`, `other`, and `insurance`. POD is required by default. The current accepted rate confirmation is required. Lumper evidence is required for an approved lumper claim; detention uses Phase 1F evidence metadata and never invents duration or facility fault. References must match tenant and load; foreign/wrong-load references fail without exposing the record.

Presence is not authenticity. No raw file, URL, binary, OCR text, token, or signed link enters a readiness case, package, or audit summary.

## Rate binding, base charge, and calculation

The evaluator selects the newest same-tenant/load Phase 1B extraction and requires `accepted` without `superseded_by`. Its ID, document, revision, and version are frozen. A superseding extraction makes an older basis stale.

Base charge selection is deterministic: accepted `total_rate`, then accepted `linehaul_rate`, otherwise insufficient data. Load profitability, RPM, mileage multiplication, expenses, and expected revenue are never substituted.

Money uses `Decimal`, two-place half-up normalization, finite nonnegative inputs, and one controlled currency (`USD`). The pure formula is base + approved accessorials − approved deductions. Mixed currency and negative final totals fail. The snapshot includes the policy marker, line items, accepted rate binding, and totals. Equal inputs yield equal output with no clock, network, OCR, or AI.

## Accessorials, detention, lumper, and deductions

Controlled accessorial types are detention, lumper, layover, stop-off, driver assist, TONU, redelivery, storage, toll, and other-controlled. IDs and lifecycle metadata are server-controlled. Proposed records remain evidence-required or review-pending until finance/owner/admin review; only approved items calculate. Rejected/approved history is retained.

Lumper amounts are manual proposals backed by same-load `lumper` receipt metadata; no extraction or authenticity claim occurs. Detention duration comes only from Phase 1F. A dollar amount still requires explicit commercial support and reviewed evidence; time alone never creates a charge. The calculation supports approved controlled deductions/credits, while no automatic or punitive deduction is generated.

## Readiness items, findings, evaluator, and refresh

Checks cover delivery confirmation, Delivered stage, current execution, POD, current RC, base charge, accessorial/deduction resolution, and blocking exceptions. Required missing/insufficient data fails. Findings are controlled, bounded, and preserve resolution evidence. Evaluation freezes current snapshots and produces a deterministic verdict. Refresh rebuilds evidence and calculation, increments version, resets pending state, and cannot auto-approve.

## Roles, approval, invalidation, and integration

Operations/dispatch may create a case and attach same-load evidence. Finance/owner/admin may refresh, evaluate, and review accessorials. Only owner/admin performs final readiness approval, reopening, and invoice/package creation. Approval rereads load/session/rate/documents/exceptions and recalculates; stale calculations return 409.

Billing-material document creation, Phase 1B acceptance/supersession, Delivered-stage reversal, and Phase 1F delivered-session correction/exception paths invoke one tenant-scoped `invoice_readiness.material_change_invalidated` helper after the parent audit starts and before the authoritative mutation. The helper uses case ID/status/version guards. A lost race returns 409 and blocks the parent mutation. An approved case becomes `reopened`; a ready/review case becomes `review_pending`. Both return to a pending verdict, receive a controlled `calculation_stale` finding, and require refresh, evaluation, and human approval again.

Approval metadata and the previous calculation/fingerprint are appended to bounded `basis_history`; nothing restores approval automatically. A later parent-write failure leaves readiness conservatively invalidated. Adding a missing POD may improve the next evaluation but never auto-approves. A case with invoice creation in progress, or an already invoiced case, blocks upstream billing-material mutation with 409 pending a future correction/credit/rebill workflow.

Current Rate Confirmation selection is deterministic: candidates sort by revision, version, update marker, and ID. Only the newest record may qualify. It must be accepted, non-superseded, same tenant/load, and reference an existing same-tenant/load document whose canonical type is exactly `rate_con`. The evaluator never falls back to historical acceptance when the newest record is draft, rejected, superseded, or has a broken document relationship.

Evaluation stores a server-controlled SHA-256 financial-basis fingerprint over bounded delivery session ID/version/state, billing-document IDs/type/upload marker, RC extraction ID/version/revision/document, accessorial and deduction identity/version/status/amount/currency, and the Decimal calculation. Raw content, URLs, notes, credentials, and signed links are excluded. Final approval compares this complete current fingerprint with the reviewed fingerprint, so a same-dollar RC or POD replacement is still stale.

## Package, invoice, duplicates, and partial failures

An approved case creates an `ipk_…` package containing only bounded references and a SHA-256 canonical hash, then an `inv_…` invoice using the server calculation. The invoice state is `ready_for_submission` and external submission is explicitly `not_submitted`. An application guard blocks another active invoice for the same tenant/load/readiness basis.

Invoice creation rereads the load, delivery session, documents/POD, exact RC relationship, accessorials, deductions, exceptions, currency, and Decimal calculation. Drift reopens the case and returns 409 before artifacts exist. After read-only validation the order is parent invoice audit, atomic readiness-case creation claim, package insert, invoice insert, guarded readiness finalization, and terminal audit.

The server-only creation state is `none`, `creating`, `ready`, or `reconciliation_required`. The claim binds the observed approved case version and approved basis fingerprint to a generated operation, reserved invoice ID, and reserved package ID while incrementing the case version. Only one concurrent caller can match; losers return 409 and create no artifacts. This removes the former read-before-insert race.

Only the claim winner creates the bounded package and `ready_for_submission` invoice. Package failure creates no invoice and marks the claim for reconciliation. Invoice failure preserves its package and marks reconciliation. A readiness-finalization race preserves both artifacts, marks reconciliation where the operation still owns the claim, and returns 409. Retries cannot claim a `creating`, `ready`, or reconciliation-required case and therefore cannot create a second package or invoice. Nothing is deleted or automatically rolled back/reapproved. Production hardening still recommends a partial unique active-invoice index and a transactional outbox; cross-collection transactions remain future work.

## API and audit behavior

Routes provide bounded case lists/reads, load case create/read, refresh/evaluate/submit-review, evidence, accessorial create/approve/reject, block/reopen/approve, invoice creation, and package read. Mutation schemas forbid unknown fields. Tenantless actors receive 403 and cross-tenant resources are invisible/404.

Controlled audit vocabulary includes readiness create/update/refresh/evaluate/review/evidence/approval/block/reopen/invalidation, accessorial create/update/approve/reject, package creation/supersession, and invoice create/ready-for-submission. Audit starts before primary mutation; inability to record it returns 503. Audit summaries allow only bounded IDs, type, totals, currency, fields, and versions.

## Recommended production indexes

- `invoice_readiness_cases`: `(tenant_id,id)`, `(tenant_id,load_id)`, `(tenant_id,status,updated_at)`, `(tenant_id,verdict,updated_at)`, `(tenant_id,invoice_id)`
- `invoice_packages`: `(tenant_id,id)`, `(tenant_id,readiness_case_id)`
- `invoices`: `(tenant_id,package_id)`, and a partial unique index on `(tenant_id,load_id)` for active invoice states

No indexes or migrations are applied to a real database in Phase 1G.
