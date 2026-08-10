# Phase 2D Backend Modularization

## Purpose

`server.py` combined application bootstrap with unrelated authentication, fleet, load,
document, billing, audit, dashboard, compliance, seed, simulation, and health behavior.
Phase 2D decomposes that application monolith without changing API or domain behavior.

Before this refactor, `server.py` was 1,366 lines. After extraction it is 95 lines and
acts as the preserved `server:app` deployment entrypoint.

## Architecture

```text
server.py (construction and wiring)
  -> app/api/*_routes.py (HTTP adapters and legacy-compatible orchestration)
     -> app/application/invoice_authority_query.py
        -> domain authority policy + tenant-scoped persistence
  -> existing Phase 1/2 route modules
  -> app/runtime.py (narrow DB/settings wiring)
```

Dependency direction is one way: the bootstrap imports routers; routers, application
helpers, domain modules, and infrastructure do not import `server.py`.

## Extracted Routers

- `auth_routes.py`: signup, login, and current-user APIs.
- `fleet_routes.py`: truck and driver CRUD.
- `load_routes.py`: load CRUD and stage mutations.
- `activity_audit_routes.py`: legacy activity and append-only audit reads.
- `document_routes.py`: document reads and document-create mutation orchestration.
- `legacy_invoice_routes.py`: historical invoice compatibility APIs.
- `demo_routes.py`: seed, simulated provider APIs, alert simulation, and the local
  rule-based assistant. The name intentionally makes non-production behavior clear.
- `query_routes.py`: dashboards, assumptions, profitability analysis, and compliance.
- `health_routes.py`: root, liveness, and configuration-readiness APIs.

The existing passport, rate-confirmation, party-verification, execution-eligibility,
pickup-release, in-transit, and invoice-readiness routers remain independently
registered.

## Shared Wiring and Compatibility

`app/runtime.py` owns shared DB/settings proxies and the small legacy serialization and
database error helpers. `server.py` configures those proxies with getters. This keeps a
single live database/settings authority while preserving tests that replace `server.db`
or `server.settings`; extracted modules do not retain stale module-global copies.

`server.py` continues to expose `app`, `db`, `client`, settings, authentication and
capability dependencies, shared helper names, `enforce_seed_config`, and the historically
directly-tested `ai_chat` handler. Application import does not execute a query, migration,
index operation, seed, worker, or external provider call.

Canonical invoice evidence lookup moved to
`app/application/invoice_authority_query.py`. It delegates classification to the Phase 2C
domain helper and does not duplicate authority policy.

## Parity and Behavior

The automated Phase 2D test inventories 167 registered method/path pairs, asserts there
are no duplicates, and verifies all 43 routes formerly declared in `server.py`. It also
checks the extracted import graph and the `server:app` compatibility boundary.

The refactor intentionally preserves:

- request and response models, status/detail behavior, authentication, capabilities,
  tenant filters, and safe serialization;
- audit-first ordering and terminal audit outcomes;
- load and document impact planning, invalidation, and conservative parent-failure
  behavior;
- Phase 2B operation/outbox/reconciliation behavior and Phase 2C canonical invoice
  authority;
- dashboard, profitability, compliance, seed, local assistant, and simulated endpoint
  calculations;
- Phase 2A production-integrity simulation blockers and health/readiness claims.

No frontend files, dependencies, product capabilities, external integrations, schemas,
domain transitions, migrations, indexes, or deployment configuration were changed.

## Intentionally Deferred

Route functions still contain the existing orchestration and direct Mongo queries where
moving them into repositories or services would increase semantic risk. The simulation
module is deliberately large because its seed models and mock-provider behavior form one
explicitly non-production boundary. The query module similarly keeps existing dashboard,
analysis, and compliance calculations together without introducing a Phase 2F projection.

Phase 2E may build real document infrastructure without changing this route boundary.
Phase 2F may introduce Control Tower projections/action-center queries without treating
the current dashboard query module as a persisted read model.
