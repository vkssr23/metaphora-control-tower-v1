# Phase 1B — Rate Confirmation Intelligence

## Purpose and limits

Phase 1B adds tenant-owned, revisioned, structured rate-confirmation intake and deterministic human review to the Verified Load Passport. It does not perform live OCR, use AI extraction, verify document authenticity, or externally verify broker or shipper identity. Manual and structured values require human review; confidence is not proof of correctness.

## Extraction model and lifecycle

`rate_confirmation_extractions` records use server-generated `rcx_` IDs, server-owned tenant/actor/timestamp fields, immutable load/document relationships and source-document snapshots, revision starting at 1, and optimistic version starting at 1. The lifecycle is `draft → review_pending|discrepancies_found → accepted|rejected`, `rejected → review_pending`, and `accepted → superseded`. Accepted records are immutable except for controlled supersession. Conditional final writes match tenant, ID, observed status, and observed version.

Supported client sources are `manual` and owner/admin `structured_import`. `system` is backend-reserved; `future_ocr` and `future_ai` are vocabulary reservations rejected for client creation. Manual extractions cannot carry client confidence at creation or update. Structured-import confidence is owner/admin-only, field-bounded to 0–1, informational, and never verification, authenticity evidence, or trust proof.

## Controlled fields

The schema covers document identifiers and dates; broker/carrier/shipper/consignee data; rates, surcharges, fees and operational charges; commodity, weight, equipment, pieces and mileage; pickup/delivery identity, address, date, time and reference values; and bounded special instructions, temperature, seal, lumper, detention and payment terms. Unknown fields and protected fields return 422. Dates and times use ISO syntax, emails are validated, phones use a conservative character/length rule, numeric values must be finite and non-negative, and null means “not supplied.” Raw text, raw OCR, file content, URLs, storage secrets, credentials and authorization data are excluded.

## Deterministic comparison

Names and locations are trimmed, internal whitespace is collapsed, and text is compared case-insensitively. Addresses remain conservative exact normalized comparisons; there is no fuzzy or AI matching. Numeric tolerance is 0.01. Dates compare ISO calendar dates and times compare `HH:MM`. Stored values are never silently normalized or changed.

Initial discrepancy vocabulary includes total/linehaul rate, mileage, pickup/delivery location/date/time, broker name/MC, commodity, weight, equipment, customer reference, missing rate/pickup/delivery/broker, and replacement rate confirmation. Severities are info, warning, and blocking. Blocking includes total rate, pickup/delivery location or date, broker identity when comparable, equipment, and missing rate/pickup/delivery. Resolutions are unresolved, accepted as document/load, corrected document/load, and waived.

## Review, roles, and acceptance

Operations/dispatcher create and edit manual drafts, compare, submit, and handle non-financial differences. Finance owns financial discrepancies. Owner/admin may use structured import, resolve all discrepancies, waive with a bounded reason, accept, reject, and supersede. Viewer access is read-only. The backend is authoritative.

Each discrepancy decision uses the controlled choices `keep_load_value`, `use_document_value`, or `corrected_value`; arbitrary MongoDB field names are never accepted. A reusable controlled-field validator validates and normalizes every `corrected_value` against the corresponding extraction/canonical constraint before it may enter reviewer resolutions, accepted evidence, or a load update. Acceptance re-reads tenant-owned extraction, load and document, recalculates comparison, requires all blocking items to be resolved or owner/admin-waived, creates an immutable accepted snapshot, and updates only selected canonical fields. RPM and profitability are server-calculated.

## Passport and failure safety

Material canonical changes use the Phase 1A conditional passport pre-invalidation before the load write. A lost passport race returns 409 without updating the load or accepting the extraction. A later failure leaves the passport conservatively invalidated; approval and pickup authorization are never restored automatically. Acceptance marks the rate-confirmation checkpoint pass as an internal administrative review, updates bounded evidence, and resets/recalculates affected load/profitability evidence without reactivating approval. Incomplete cross-collection operations require audit-ledger reconciliation; production transactions/outbox workers remain future work.

Every mutation begins a Patch 0D audit event. Metadata is bounded to identifiers, revision/version, controlled field names, discrepancy identifiers/types, and passport identifiers; it excludes request bodies and sensitive content. Tenant predicates protect every lookup and mutation, so cross-tenant identifiers return 404.

## API and indexes

The API provides tenant-scoped global/load/document lists, get, create, draft update, compare, submit, resolve, accept, reject, return-to-review, and supersede actions. Lists are bounded and deterministically sorted; `_id` is excluded and no delete route exists.

Recommended (not applied) indexes: `(tenant_id,id)`, `(tenant_id,load_id,created_at)`, `(tenant_id,document_id,revision)`, `(tenant_id,status,updated_at)`, `(tenant_id,load_id,document_id,accepted_at)`, and unique `(tenant_id,document_id,revision)`.

Future integration points are controlled backend population from OCR/AI, background ingestion and cross-collection transactions/outbox. They must preserve this human review, source labeling, tenant isolation, audit-first behavior, and sensitive-data exclusions.
