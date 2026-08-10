# Phase 2F — Exception & Action Center Foundation

## Purpose and authority

The Action Center is a tenant-scoped, deterministic work-queue projection. Phase 1 and Phase 2 domain records remain authoritative. Acknowledging an action changes only projection metadata; it never clears a source exception, authorizes pickup, verifies a party, establishes eligibility, records POD, approves an accessorial, approves an invoice, or resolves reconciliation.

Policy version: `action-center-v1`. There is no AI, LLM, autonomous execution, external provider, live GPS, live weather, email, accounting, or dispatch integration.

## Lifecycle, identity, and recurrence

Items use `open`, `acknowledged`, and `resolved`. `acknowledged` means seen, not fixed. Refresh resolves an active item only when its detector no longer observes the source condition. There is no manual resolve endpoint.

Stable active identity hashes source type, source ID, reason code, entity type, and entity ID. Repeated refresh upserts the same active incident and preserves acknowledgement. After source-derived resolution, recurrence uses the maximum historical generation plus one and retains resolved history. A partial unique index permits one active identity while retaining resolved generations. Identical incident output is deduplicated and controlled supporting reason codes remain visible. There is no general cross-detector root-cause correlation: related party, eligibility, and pickup cards may remain separate when they represent distinct owned work.

## Categories, severity, ownership, and ordering

Categories are `execution`, `safety`, `fraud_risk`, `documents`, `finance`, `reconciliation`, and `platform_integrity`. Severity is `critical`, `high`, `medium`, or `low`. Owners use existing vocabulary: `operations`, `safety`, `finance`, and `admin`. Mapping is server policy; clients cannot choose it.

Queue order is severity (critical first), then unacknowledged before acknowledged, then oldest `first_detected_at`, then ID. Age is derived by the server. Phase 2F defines no contractual or invented SLA.

## Source matrix

| Source | Condition | Reason | Category | Severity | Owner | Recommended action |
|---|---|---|---|---|---|---|
| Pickup release/passport authorization | blocked/review/revoked/exception or authorization revoked | `pickup_release_blocked`, `pickup_authorization_revoked` | execution | high | operations | Review pickup release/prerequisites |
| Party verification | review pending/required, findings open, blocked, expired, revoked | `party_verification_required` | fraud risk | high/critical from explicit critical source risk | safety | Review party evidence |
| Execution eligibility | review pending/required, blocked, expired, revoked | `execution_not_eligible` | safety | high | safety | Review eligibility prerequisites |
| Execution exception | any non-resolved/waived/closed exception | `active_execution_exception`, `detention_active` | execution | source-controlled/normalized | operations | Review exception/detention |
| Execution session | current manual delay snapshot says delayed without exception card | `delivery_delay` | execution | high | operations | Review execution progress |
| Load/documents | Delivered/Closed without POD metadata | `pod_missing_after_delivery` | documents | high | operations | Record current POD evidence |
| Invoice readiness | draft/review/blocked/reopened | `invoice_readiness_blocked` | finance | medium | finance | Review prerequisites |
| Accessorial | not approved/rejected/waived | `accessorial_approval_required` | finance | medium | finance | Review accessorial |
| Reconciliation item | open/acknowledged | `operation_reconciliation_required` | reconciliation | high/source-controlled | admin | Use reconciliation workflow |
| Persisted integrity finding | open high/critical | `platform_integrity_critical` | platform integrity | high/critical | admin | Review integrity finding |

Evidence references expose only controlled entity type/ID pairs. No raw source record, document bytes, storage key, credential, audit payload, or exception free text is copied.

Phase 1F permits category-aware individual assignment roles. Phase 2F intentionally maps execution-exception queue ownership to `operations` for this pilot; it does not copy the assigned source user or reinterpret source assignment authority.

## Projection refresh, consistency, and rebuild

`GET /api/action-center`, summary, and detail perform a tenant-bounded reconciliation before returning. Each source collection requests up to 5,001 records. Zero through exactly 5,000 records proves completeness; 5,001 means the source exceeds the pilot cap and the entire refresh fails closed with 503 before projection persistence. Request pagination (50 default, 200 maximum) separately limits response size. This avoids false clearing from truncated sources, global cross-tenant scans, and N+1 per-card reads. It is request-driven, not real-time: the queue is current as of `refreshed_at`. Source changes become visible on the next successful Action Center request. A query, detector, completeness, or projection failure preserves the existing projection and does not roll back or mutate source state.

Current active cards can be rebuilt from current source records. Deleting `action_items` would lose acknowledgement, resolved-incident, and original first-detection history unless restored from backup; those histories are not reconstructable from current source state alone. No destructive rebuild, TTL, migration, scheduler, worker, or index application is included.

## API and permissions

- `GET /api/action-center`: active default; controlled status, severity, category, owner, load and acknowledgement filters; offset pagination; default 50, maximum 200.
- `GET /api/action-center/summary`: active counts using the same lifecycle vocabulary.
- `GET /api/action-center/{id}`: safe tenant-scoped detail.
- `POST /api/action-center/{id}/acknowledge`: authenticated, tenant-scoped, version-guarded, audit-first, server actor/time, idempotent after acknowledgement.

All authenticated roles can read their tenant queue. Operations-owned items require operational capability, safety/fraud items require safety capability, finance items require finance capability, and admin/reconciliation/platform-integrity items require owner/admin. Owner/admin may acknowledge across categories. Invalid owner/category combinations fail closed; viewers cannot acknowledge.

## Operator UI and limitations

Operators can view, filter, acknowledge when their existing role plausibly matches ownership, and navigate toward the source workflow. Backend authorization remains authoritative. The pilot UI shows the first 50 highest-priority matching active items and has no page controls; the summary API exists but is not displayed. The page uses only backend results and includes loading, error, and empty states. It makes no claim of automatic remediation, AI root-cause analysis, live GPS, autonomous dispatch, automatic safety clearing, or automatic invoice approval. Offline CAS policy is tested; real Mongo unique-index/concurrency behavior remains unverified pending real-Mongo validation and index rollout. Streaming, WebSockets, mutation-triggered refresh, production scheduling, retention policy, and provider integrations are deferred.
