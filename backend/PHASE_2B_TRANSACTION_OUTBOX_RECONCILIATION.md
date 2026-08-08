# Phase 2B — Transaction, Outbox & Reconciliation Core

## Problem and guarantees

Phase 2B makes important multi-record commands observable, idempotent, retry-safe, and reconcilable without claiming that the deployed Mongo topology supports transactions. It adds three separate tenant-scoped ledgers: `operations` for command intent/progress, `outbox_events` for durable post-commit work, and `reconciliation_items` for unresolved partial or ambiguous outcomes.

The current invoice pilot runs in explicit `durable_saga` mode. It provides guarded writes, durable progress, forward recovery, and at-least-once outbox processing. It does **not** provide multi-document atomicity, exactly-once delivery, distributed transactions, destructive compensation, or a deployed worker.

## Operation registry and idempotency

An operation records a bounded server-defined type, target, actor, request ID, audit linkage, execution mode, lifecycle, version, safe result reference, controlled failure information, and six invoice steps. It never stores request bodies, credentials, document contents, or exception dumps.

Invoice idempotency identity is `(tenant_id, operation_type, target_type, target_id, idempotency_key)`. `Idempotency-Key` is optional, limited to 128 safe characters, and bound to the authenticated tenant on the server. A successful replay reads the prior invoice and never reruns mutation. Active work returns conflict. Failed/terminal or reconciliation-required work returns controlled conflict and is not blindly retried. A unique partial index is declared but is not automatically applied.

The unique index includes only records whose `idempotency_key` has Mongo string type; stored `null` and missing keys are excluded. The offline collision scanner implements the same `$type: "string"` rule. If a concurrent winner succeeds after another request's initial lookup but before operation creation, `create_or_replay` returns the winner and the route immediately reconstructs the tenant-scoped invoice, package, readiness, and outbox boundary. The losing HTTP attempt records its own audit `started → rejected` no-op with `idempotent_replay`; it never writes under the winner's audit identity.

Operation lifecycle is `planned → started → committing → succeeded`, with terminal alternatives `failed`, `partial`, and `reconciliation_required`. `succeeded` is written only after invoice authority and its required outbox event exist. Steps are server-controlled: `operation_started`, `readiness_claimed`, `package_created`, `invoice_created`, `readiness_finalized`, and `outbox_recorded`. Every update uses the operation version as an optimistic guard.

The lifecycle graph is enforced before any durable update. Active states may advance normally or enter a controlled failure branch. `succeeded`, `failed`, `partial`, and `reconciliation_required` are terminal to the generic transition primitive; recovery from them requires a future explicit command. Completed, failed, and skipped steps cannot regress, and advancing steps must follow server-defined order.

## Unit-of-work strategies

`DurableSagaUnitOfWork` explicitly reports `atomic_multi_document_writes=False` and `transaction_capability=unverified`. It does not wrap ordinary writes in a context manager or describe them as atomic.

`TransactionalUnitOfWork` accepts only an explicitly supplied, already-verified session. No session is started, no topology is probed, and `MONGO_URL` never implies support. `required` plus unavailable fails with `transaction_required_but_unverified`; `preferred` plus unavailable selects saga with an explicit warning; `disabled` uses saga. Real Mongo commit, abort, transient labels, topology, and concurrency remain deployment-gated verification work.

## Invoice pilot ordering and failures

Audit start remains first. A new request then persists operation intent before the existing readiness claim. The authoritative order is:

```text
audit STARTED
  → operation STARTED
  → guarded readiness claim
  → immutable invoice package
  → server-calculated invoice (ready_for_submission / not_submitted)
  → guarded readiness finalization
  → invoice.ready_for_submission outbox event
  → operation SUCCEEDED
  → audit SUCCEEDED
```

Failure behavior is forward-only:

- Audit-start failure: no operation or business mutation.
- Operation-intent failure: no business mutation; terminal audit failure is attempted.
- Package failure: no invoice; claim and operation become reconciliation-required.
- Invoice failure: package is preserved; operation and readiness require reconciliation.
- Finalization race: package and invoice are preserved; no false success; reconciliation is opened.
- Outbox failure after invoice: invoice and package are preserved; operation is not successful; reconciliation is opened.
- Final operation-success update failure after outbox: invoice, package, finalized readiness, and outbox are preserved; clean HTTP success is withheld; reconciliation is attempted independently and the operation is guarded toward `reconciliation_required` where possible.
- Repeated reconciliation retry: the operation identity fails closed and cannot duplicate artifacts.

If reconciliation persistence and guarded operation recovery both fail at that final boundary, the operation remains `committing`. The integrity scanner emits `OPERATION_STRANDED_AFTER_OUTBOX` when its invoice, package, and required outbox evidence are present. No automatic repair or mutation replay occurs. Same-key retry sees active/reconciliation state; different-key and no-key retries are blocked by final Phase 1G invoice authority.

The existing current-delivery reread, POD/document evidence, accepted rate confirmation, accessorial review, deterministic calculation, basis fingerprint, readiness claim, package-before-invoice ordering, `ready_for_submission`, and `not_submitted` rules remain intact.

## Outbox lifecycle, leases, and worker

Outbox event types and payload fields are allowlisted. Payloads are scalar, bounded, versioned, and contain identifiers only. The invoice pilot emits exactly one `invoice.ready_for_submission` record per operation/aggregate identity.

Lifecycle is `pending → processing → delivered`, with `processing → retryable → processing` and terminal `dead_letter`. A worker scans tenant-ready records, then wins work only through a conditional update over record ID, status, version, and prior claim token. The claim sets a server-controlled owner/token/expiry, increments attempt count and version, and records attempt time. An active lease is not duplicated. An expired lease can be reclaimed. Delivery/failure requires owner, token, version, and processing status, so a stale worker cannot finalize after reclaim.

Retry delay is deterministic exponential backoff: 30, 60, 120 seconds and so on, capped at one hour. Five attempts exhaust policy. Unknown handlers dead-letter immediately rather than silently dropping work. Handler errors store only controlled codes and safe bounded summaries. The worker is an internal function with no external handlers, daemon, scheduler, broker, or deployment wiring.

At-least-once means a handler can run before a worker loses confirmation of its delivery update. Future handlers must therefore be idempotent. Exactly-once external side effects are explicitly not claimed.

```text
pending/retryable (available) → guarded claim + lease → internal handler
    success → guarded delivered
    retryable failure → guarded retryable + deterministic next_attempt_at
    terminal/unknown/exhausted → guarded dead_letter
worker death → lease expires → another guarded claim; old token is stale
```

## Reconciliation lifecycle

Reconciliation items are tenant-scoped and deduplicated by tenant, operation, reason, entity type, and entity ID. Controlled states are `open`, `acknowledged`, `resolved`, and `dismissed`. Phase 2B creates open finance-owned items but adds no mutation API or automatic resolution. Later resolution must identify and audit the human/system actor. Financial or safety evidence is never deleted to simulate rollback.

## Separation and observability

Audit events answer who attempted a mutation and its terminal outcome. Operations answer command intent, steps, retry safety, and authoritative success. Outbox events describe durable downstream work. Phase 1F execution events remain historical freight-execution facts. These records are correlated but not conflated: the invoice operation ID is also the audit operation ID, and the request middleware ID is copied into the operation. Logs must identify safe IDs/types/results without payloads or secrets.

## Integrity and readiness

The declarative index manifest now covers tenant identities, idempotency, required event deduplication, reconciliation deduplication, worker queues, operation status scans, and open reconciliation queues. No code applies indexes. The read-only integrity scanner recognizes the new tenant/version/parent relationships and reports missing operation links, missing required invoice outbox records, missing reconciliation, expired leases, and dead letters.

Environment metadata honestly reports `transaction_capability=unverified` and `transaction_mode=durable_saga`. Worker existence is not provider or integration readiness.

## Sequence summaries

```text
Idempotent replay: validate tenant-bound key → find succeeded operation → read safe invoice reference → return invoice; no writes
Package failure: audit/operation/claim → package insert fails → readiness + operation reconciliation_required → one reconciliation item
Invoice failure: package committed → invoice insert fails → preserve package → reconciliation_required
Finalization race: package + invoice committed → guarded readiness update loses → preserve evidence → reconciliation_required
Outbox failure: invoice authority finalized → event insert fails → never mark operation success → reconciliation_required
Worker retry: available event → lease claim → safe failure → backoff → lease claim → delivered/dead-letter
```

## Phase 2C boundary and remaining gates

Phase 2C may consume operation/outbox/reconciliation state when centralizing mutation impact and invalidation. Phase 2B does not implement an impact planner, generic workflow engine, event sourcing, CQRS, integrations, frontend work, migrations, production index application, or deployment. Before enabling transactional mode, real Mongo topology/session behavior, commit ambiguity, transient transaction labels, indexes, and worker concurrency must be verified in an approved disposable environment and then in deployment readiness—not inferred from offline fakes.
