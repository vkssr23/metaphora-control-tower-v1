# Phase 1C — Party Verification Core

## Purpose and limitations

This phase adds tenant-owned internal administrative review cases for load parties, evidence metadata, contacts, pickup instructions, and deterministic risk signals. Results mean only “administratively reviewed,” “internally matched,” “evidence present,” “unresolved,” “cleared for internal workflow,” or “blocked.”

There is no live FMCSA/SAFER verification, insurance-provider validation, identity-provider verification, domain-ownership verification, fraud-database lookup, document-authenticity verification, or AI fraud scoring. No external API is called. Results are internal administrative review decisions only.

## Case model and lifecycle

`party_verification_cases` is tenant-owned. Server-controlled identifiers use `pvc_`; tenant, actor, timestamp, snapshots, findings, risk, status, and version fields cannot be supplied by clients. Load and passport bindings are immutable and one case is allowed per tenant/load. There is no delete route.

The lifecycle is `draft → review_pending`; review can move to `findings_open`, `cleared`, or `blocked`; blocked, expired, and revoked cases may return to review; cleared cases may expire or be revoked. Final mutations match tenant, ID, observed status, and observed version and return 409 on a lost race. Cleared cases cannot be generally edited.

## Review domains and roles

Domains are broker identity, shipper identity, carrier authority administrative review, insurance evidence, contact validation, pickup instructions, and fraud risk. Operations/dispatch owns operational domains; safety/compliance owns carrier and insurance; finance owns defined contact, insurance, and risk review; owner/admin can review all domains. Only owner/admin can waive, clear, block, expire, or revoke. Viewers are read-only.

Only `manual` client sources are accepted. `system` is server-reserved and `future_fmcsa`, `future_insurance`, `future_identity`, and `future_fraud_provider` are rejected as client sources.

## Snapshots and evidence

Snapshots use bounded allowlists from the canonical load, accepted rate-confirmation snapshot, Load Passport, tenant record, and document metadata. Missing repository fields remain missing and create findings; no authority status is invented. Documents retain only ID, bounded filename/type, upload actor, and upload time. Contents, URLs, signatures, credentials, bank data, and full policy numbers are excluded. Insurance evidence is administrative metadata only; stated dates may later support deterministic warnings but do not establish policy validity or authenticity.

## Deterministic comparison and risk

Email comparison trims, case-folds, and collapses whitespace. Phone normalization retains digits only. Pickup address, reference, equipment, and commodity use normalized exact comparisons against accepted rate-confirmation data. No fuzzy matching, messages, callbacks, mailbox checks, domain ownership checks, OCR, or reputation lookup occurs. Free-email domains are informational.

Controlled findings include the initial broker, shipper, carrier, insurance, pickup, and risk vocabulary. The implemented baseline emits missing broker identifier, broker name mismatch, missing shipper contact, missing carrier USDOT/MC, missing insurance document, pickup address/number/equipment/commodity mismatch, missing pickup reference, and informational free-email inconsistency signals. Findings never label a party fraudulent.

Risk weights are info 2, warning 10, high 25, critical 50, capped at 100. Levels are low below 20, moderate 20–49, high 50–74, and critical at 75+ or with a critical finding. Open blocking and critical findings prevent clearance. The score is an internal workflow indicator, never a fraud probability.

## Clearance, invalidation, and passport integration

Clearance requires review status, every required domain completed without a negative/pending result, no open blocking or critical signal, and the bound passport version still current. Owner/admin is authoritative. Clearance updates only broker identity, shipper identity, and pickup-instruction passport checkpoints as internal system decisions; it never passes driver, truck, trailer, external authority, external insurance, authenticity, or fraud-free checkpoints.

Material broker, shipper, pickup, and reference changes pre-invalidate cleared cases with status/version guards before the load write, clear clearance, reset affected domains, and record `material_change_requires_reverification`. Existing Phase 1A invalidation concurrently resets passport checkpoints and revokes pickup authorization. A lost invalidation race stops the canonical write; a later canonical failure leaves the conservative invalidation in place. Clearance is never restored automatically.

## Audit, isolation, and failure policy

Every case mutation begins a Patch 0D audit operation. Audit-start failure returns 503 and blocks mutation; terminal-audit failure does not corrupt a successful primary result. Metadata is bounded and allowlisted. Reads, evidence relationships, and mutations use authenticated tenant predicates; foreign IDs appear as 404.

Cross-collection operations use conservative ordering and conditional guards. MongoDB transactions/outbox processing remain future work, as do external authority/insurance/identity/fraud providers, callbacks, background workers, and production indexes.

Recommended (not applied) indexes: `(tenant_id,id)`, `(tenant_id,load_id)`, `(tenant_id,status,updated_at)`, `(tenant_id,risk_summary.risk_level,updated_at)`, `(tenant_id,passport_id)`, and a unique tenant/load active-case index.

## Phase 1C.1 clearance integrity

Cleared cases are immutable through update, refresh, evaluate, domain-review, finding-resolution, and evidence-attachment routes. Evaluate/refresh accept draft, review-pending, and findings-open cases; domain reviews also accept those statuses; findings may be resolved only in review-pending or findings-open; evidence may be attached in draft, review-pending, findings-open, or blocked. Expired and revoked cases must use the dedicated return-to-review transition first.

`insurance` is the sole supported qualified insurance-evidence document type. BOL, POD, invoice, rate confirmation, lumper, scale, `other`, and generic metadata never satisfy the insurance prerequisite. Qualified evidence means only that bounded evidence metadata is administratively present; it does not mean policy authenticity or active coverage has been externally verified. Stated expiration dates generate deterministic administrative warnings.

Clearance fails closed with stable reasons for incomplete domains, unresolved blocking findings, unresolved critical signals, missing qualified insurance evidence, a missing accepted same-tenant/same-load rate-confirmation extraction when rate-confirmation evidence exists, passport-version drift, or snapshot drift. The route starts audit evidence, re-reads every relationship, calculates the synchronization, conditionally increments and updates the passport first, and only then conditionally clears the case. A passport race never clears the case. A later case race never restores an older passport, approval, or pickup authorization.

The centralized material-change policy covers broker and shipper identity, pickup location/time/reference, equipment, commodity, weight, assignments, qualified insurance evidence, pickup/contact evidence, and accepted rate-confirmation evidence. Affected domains and only the relevant passport checkpoints reset. Direct load writes, qualified document creation, and rate-confirmation acceptance conservatively pre-invalidate cleared cases and increment affected passport versions before their canonical writes. Lost invalidation races prevent the canonical mutation; later canonical failure leaves clearance, approval, and pickup authorization invalidated. Nothing is automatically restored.
