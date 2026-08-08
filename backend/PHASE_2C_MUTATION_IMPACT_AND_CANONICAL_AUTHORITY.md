# Phase 2C — Mutation Impact and Canonical Authority

## Purpose and boundary

Phase 2C centralizes the server-controlled answer to “what downstream domains are affected by this mutation?” The policy is not a workflow engine, is not tenant configurable, performs no MongoDB access, and never grants positive authority. Existing domain helpers remain responsible for how a Passport, verification case, eligibility case, pickup release, execution session, or invoice-readiness case moves conservatively.

The pure policy is `app/domain/mutation_impact.py`. `app/infrastructure/impact_executor.py` defines a bounded, tenant-required handler contract for orchestration that benefits from a generic executor. Existing audit-first routes retain their carefully ordered target-specific orchestration and consume the central plan to select targets and change types.

Policy version: `mutation-impact-v1`. A deterministic `mip_<sha256>` plan ID binds the policy version, source identity and type, mutation type, derived material fields, and ordered impacts. It contains no record snapshot or secret and is not an authorization token.

## Controlled policy

Supported sources are `load`, `document`, `rate_confirmation`, `party_verification`, `execution_eligibility`, `pickup_release`, `execution_session`, `invoice_readiness`, and `invoice`.

Route-integrated mutations are `load.updated`, `load.stage_changed`, `document.added`, `rate_confirmation.accepted`, `rate_confirmation.superseded`, `execution.plan_amended`, and `invoice_readiness.financial_basis_changed`. Speculative mutation types for Party Verification, Eligibility, Pickup, and a nonexistent generic delivery-correction command were removed. Existing Party Verification to Pickup/Eligibility, Eligibility to Pickup, and execution-exception to Readiness wiring remains route-local and is not claimed as centralized in Phase 2C.

Actions are limited to `INVALIDATE`, `REOPEN`, `RECALCULATE`, `REVERIFY`, `REVOKE`, `MATERIAL_CHANGE`, `RECONCILE`, and `NO_ACTION`. The implemented plans only produce conservative actions; they cannot approve a Passport, clear a party, mark eligibility, authorize pickup, confirm delivery, or approve/create an invoice.

Canonical load material fields are the existing Phase 1A fields: rate, miles, pickup and delivery address/location/appointment fields, broker, customer, commodity, weight, equipment type, driver/truck assignment, and rate-confirmation number. Known UI/derived metadata (notes, risk, ETA, timestamps, RPM, and expense estimates) is non-material. Comparisons use authoritative old and proposed values; a client list is only a bounded candidate set. Missing and `None` follow current optional-schema semantics. Unknown fields fail closed into conservative review impacts rather than `NO_ACTION`.

## Dependency matrix

| Source mutation | Target | Action | Reason | Order | Race policy |
|---|---|---:|---|---:|---|
| Material/unknown load update | Pickup release | REVOKE | load material/unknown change | 10 | block parent on required conflict |
| Material/unknown load update | Load Passport | INVALIDATE | load material/unknown change | 20 | guarded version; block parent |
| Party-relevant load update | Party verification | REVERIFY | load material change | 30 | guarded version; block parent |
| Execution-relevant load update | Execution eligibility | INVALIDATE | load material change | 40 | guarded version; block parent |
| Material/unknown load update | Execution session | MATERIAL_CHANGE | load material/unknown change | 50 | guarded session control; block parent |
| Rate/RC/unknown load update | Invoice readiness | REOPEN | invoice basis changed | 60 | executed before parent write; invoiced/creating fails closed |
| Rate-con document | Pickup, Passport, Party, Eligibility | REVOKE/INVALIDATE/REVERIFY | document prerequisite changed | 10–40 | Pickup executes first; block document create on conflict |
| Insurance document | Pickup, Passport, Party, Eligibility | REVOKE/INVALIDATE/REVERIFY | document prerequisite changed | 10–40 | Pickup executes first; block document create on conflict |
| Billing document (`pod`, `rate_con`, `bol`, `lumper`, `other`, `invoice`) | Invoice readiness | REOPEN | billing document changed | 60 | invoiced/creating requires reconciliation |
| RC accepted or superseded | Pickup, Passport, Party, Eligibility | conservative actions | RC identity changed | 10–40 | every listed target is consumed; block parent on conflict |
| RC accepted or superseded | Invoice readiness | REOPEN | rate confirmation changed | 60 | same-dollar replacement remains material |
| Delivered reversal | Invoice readiness | REOPEN | delivery basis changed | 10 | block stage mutation on conflict |
| Terminal execution plan amendment | Invoice readiness | REOPEN | delivery basis changed | 10 | preserve prior plan/events; fail closed |
| Accessorial/deduction/financial basis change | Invoice readiness | RECALCULATE | invoice basis changed | 10 | issued/creating invoice blocks mutation |

Safety revocation precedes read-model/financial refresh. Existing Patch 0D route ordering remains: validate parent, begin parent audit, conservatively invalidate required downstream authority, write parent, then terminally complete the audit. A downstream version race blocks the parent mutation. If the later parent write fails, already-applied conservative invalidation remains; history is never rolled back or deleted.

## Audit, operation, and helper responsibilities

Patch 0D audit identities remain the mutation correlation authority. Plans expose their stable plan ID for future correlation but do not create a parallel operation identity. Phase 2B operations, idempotency, package creation, outbox, and reconciliation continue to wrap canonical invoice creation unchanged. No generic outbox event was added. Existing invalidation helpers retain tenant filters, current-record selection, state/version guards, audits, and exact transition semantics.

## Canonical modern invoice authority

Modern-managed evidence is deliberately narrow and repository-grounded: a Load Passport, Execution Eligibility case, Pickup Release case, Execution Session, Invoice Readiness case, or complete Phase 1G readiness/package invoice binding for the same tenant and load. Any one closes the legacy write boundary. A new load with no such evidence is `unverifiable`, not legacy, so legacy invoice creation fails closed. A Delivered load without readiness likewise cannot use the legacy create route.

An invoice carrying only `readiness_case_id` or only `package_id` is `modern_incomplete`, never legacy. Legacy records mixed with modern or incomplete evidence are `ambiguous`. Modern, modern-incomplete, ambiguous, and unverifiable classifications reject legacy create/update; only positively evidenced legacy-only invoice history retains compatibility writes. New authoritative invoice creation must follow Invoice Readiness → approved current billing basis → Invoice Package → Invoice (`ready_for_submission`). The Phase 1G deterministic billable total remains the amount authority; profitability and RPM are not substitutes.

Legacy-only invoice records remain readable and their compatibility writes remain available. Historical records are not deleted or rewritten. A load with legacy plus modern authority fails closed and is reported as `LEGACY_MODERN_INVOICE_AUTHORITY_CONFLICT`; partial modern bindings are reported as `MODERN_INVOICE_AUTHORITY_INCOMPLETE`. `load.invoice_status` is compatibility/read-model data only. Stage transitions write it only for positively classified legacy loads, never merely because readiness is absent. Existing divergence remains `INVOICE_STATUS_DISAGREEMENT`. Already-invoiced financial changes are blocked for reconciliation rather than silently reopening a second invoice. No credit/rebill workflow is invented.

## Deferred work and operational safety

Conflicting historical data still requires a later controlled migration/reconciliation decision. This phase performs no migration, backfill, production index application, real/remote database access, provider call, external integration, deployment, Action Center work, AI work, or broad `server.py` modularization. Phase 2D remains responsible for broad module extraction.
