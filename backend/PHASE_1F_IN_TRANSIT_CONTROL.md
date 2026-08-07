# Phase 1F — In-Transit Execution & Exception Control

## Purpose and trust boundary

Phase 1F starts only after Phase 1E pickup confirmation and creates a tenant-owned, versioned execution session. It is audit-first, fail-closed, append-only for events, human-controlled, and preserves the pickup authorization/custody evidence. There is one non-terminal session per tenant/load; records have server IDs, tenant, actors, and timestamps and no delete routes.

This phase has no live GPS, telematics, ELD, traffic, weather, Maps routing, geofencing, broker tracking, shipper tracking, driver-app tracking, or automatic detention proof. Manual evidence is explicitly labelled and is never described as GPS, geofence, route, recipient-identity, signature, traffic, weather, or detention verification.

## Lifecycle and execution state

Lifecycle transitions are `pending_start → active`, `active → paused|delivery_arrived|exception`, `paused → active|exception`, `exception → active|paused|delivery_arrived`, `delivery_arrived → delivery_confirmed|exception`, and `delivery_confirmed → completed|exception`. Controlled version/status predicates make a lost race a 409. Execution states are `pickup_confirmed`, `departed_pickup`, `in_transit`, `intermediate_stop`, `approaching_delivery`, `arrived_delivery`, `delivered`, and `completed`.

Start requires a same-tenant current passport and Phase 1E case with `pickup_confirmed` status/custody, consumed authorization, unchanged driver/truck assignment, and a canonical `Loaded` or `In Transit` load stage. “Released” alone is insufficient. Current-release selection sorts all same-tenant/load cases deterministically by update/create time, version, and ID. The newest current case must itself be pickup-confirmed; an older confirmed case cannot bypass a newer review, revoked, or exception case. Equal top time/version candidates fail closed as `pickup_release_ambiguous`. Foreign cases are invisible. The frozen plan contains bounded load, appointments, miles, assignments, equipment/commodity/weight, prerequisite versions, and custody state; it contains no documents, signed URLs, or external route data.

## Events and sources

`execution_events` is append-only and tenant-scoped. IDs, actor, recorded time, session version, source, and state are server-controlled. Client mutations accept only `manual`; `system` is server-only and all `future_*` sources are rejected by strict schemas. Structured data is event-specific and bounded.

## Progress, ETA, delays, stops, detention, and route status

Manual progress accepts bounded text, stop index, finite non-negative remaining miles, explicit ETA, delay estimate, and note. ETA uses only the planned appointment and explicit manual ETA. Variance up to 15 minutes is `on_time`, 16–30 is `at_risk`, and over 30 is `late`; absent inputs produce `unknown`. Delay evaluation reports only available evidence and never invents a cause.

Stops are bounded pickup/intermediate/delivery snapshots with ordered, version-guarded manual arrival/departure. Departure before arrival and out-of-order arrival return 409. Detention is manually started/ended, document references are tenant/load checked, and duration is server-calculated with no automatic billing. Manual route status can be `unknown`, `nominal`, or `possible_deviation`; it cannot assert `confirmed_deviation`.

Authoritative operational time is server-controlled. Stop arrival/departure, delivery arrival/confirmation, detention start/end, event occurrence/recording, and mutation timestamps use one server-generated UTC value per controlled mutation. Clients cannot submit `occurred_at`, `started_at`, `ended_at`, or `delivered_at`; these receive 422. Any future human-reported time must be stored separately as explicitly manual evidence and cannot replace administrative event, custody, or ordering time. Detention duration uses only the stored server start and server end.

ETA evaluation creates one server `evaluated_at`. The pure delay evaluator accepts it explicitly as `as_of` and never reads ambient time, so equal explicit inputs produce equal output.

## Exceptions, ownership, SLA, escalation, and health

`execution_exceptions` uses controlled types/categories, severities `info|warning|high|critical`, statuses `open|acknowledged|investigating|resolved|waived|closed`, server actors/times, strict versions, and no delete route. High/critical items require an owner. Owner references must resolve inside the authenticated tenant. Operational, safety/compliance, finance/fleet, and owner/admin roles are bounded; only owner/admin may waive, with a reason.

Default deterministic acknowledgement SLAs are 24 hours for info, 12 for warning, 4 for high, and 1 for critical. SLA states are `within_sla`, `due_soon` (30 minutes), and `overdue`. Escalation is an explicit human action. Health is `healthy`, `watch`, `at_risk`, or `critical`, based on unresolved severity and overdue SLA; it is server-computed.

Specific-owner requests provide only `owner_user_id`. The server resolves that user inside the authenticated tenant, derives `owner_role` from database-backed membership, and enforces category compatibility. A client-supplied `owner_role` is an unknown protected field and returns 422. Foreign users remain 404 even for owner/admin actors.

## Custody, delivery, POD, and completion

Delivery arrival is a manual, ordered delivery-stop event and makes no geofence claim. Confirmation requires arrival, correct canonical load stage, no cross-tenant evidence, and safely changes `Arrived Delivery` to `Delivered`; it makes no signature or recipient-identity claim. Delivery confirmation may occur without POD, but completion requires a same-tenant/load POD metadata record (or a future explicit owner/admin waiver policy), no unresolved blocking/critical exception, consistent custody, `delivery_confirmed`, and canonical `Delivered` stage.

Delivery confirmation uses conservative forward-safe ordering: parent audit start, guarded session confirmation, append-only delivery evidence, POD readiness evidence, canonical `Arrived Delivery → Delivered`, then terminal audit. A session race or event failure leaves the load unchanged. If a required evidence write or later load-stage write fails after session control, evidence is never deleted: the session moves to `exception`, a `delivery_confirmation_conflict` is opened where storage permits, and the route returns 409 for a stage race or sanitized 503 for storage failure. Repeated confirmation is rejected by lifecycle/version guards without duplicate success evidence.

## Material change and amendment

Once execution has started, Metaphora does not erase or silently rewrite the original execution plan when canonical load data changes. The canonical `PUT /api/loads/{id}` path integrates a pure, value-aware detector for driver/truck assignment, pickup and delivery address/appointment fields, equipment, commodity, weight, loaded miles, deadhead miles/drive estimates where the canonical schema supports them, and stage when changed by a controlled mutation path. Non-material fields and unchanged values create no event, exception, or health degradation.

The parent load audit starts first. Existing Phase 1A–1E controls run next. For an active, paused, exception, or delivery-arrived Phase 1F session, the server conditionally changes the observed session/version to conservative `exception`/`at_risk`, appends `material_change_detected`, and opens a blocking neutral `execution_plan_material_change` review exception before mutating the canonical load. Metadata contains bounded field/domain names, not request bodies or before/after dumps. Tenant predicates apply to every lookup and write.

A lost session status/version race returns 409 and prevents the load update. A required event/exception failure returns sanitized 503 and prevents the load update. If the later canonical write fails, the conservative event, exception, and health state remain as reconcilable evidence of the attempted planning change; history is never deleted or automatically restored.

The original `planned_snapshot` remains unchanged. The controlled owner/admin plan amendment endpoint saves the complete prior planned snapshot, version, actor/time, and reason in `planning_history`, then creates a new snapshot. Original pickup/custody evidence is never changed. Completed and cancelled sessions do not receive new material-change exceptions.

## API and isolation

APIs cover session list/get/by-load/start; progress/pause/resume; stop arrival/departure; detention; ETA; event/exception reads; exception create/acknowledge/assign/escalate/resolve/waive; delivery arrival/confirmation; completion; and plan amendment. Lists are bounded and deterministically sorted, `_id` is excluded, request extras produce 422, browser tenant/actor fields are absent, tenantless users receive 403, and cross-tenant IDs receive 404.

Recommended (not applied) indexes: `(tenant_id,id)`, `(tenant_id,load_id)`, `(tenant_id,status,updated_at)`, `(tenant_id,execution_state,updated_at)`, `(tenant_id,latest_event_at)`, `(tenant_id,execution_session_id,occurred_at)`, `(tenant_id,execution_session_id,status)`, and `(tenant_id,severity,status,sla_due_at)`.

Future authoritative integrations may add telematics/GPS, ELD, route/maps, traffic/weather, geofencing, broker/shipper tracking, driver apps, automatic detention, notifications/workers, transactional outbox, and production indexes. None is connected or claimed here.
