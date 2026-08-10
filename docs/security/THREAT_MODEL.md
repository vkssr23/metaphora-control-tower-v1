# Metaphora Pilot Threat Model

Status: Phase 2G engineering threat model; not a compliance certification.

## Assets and trust boundaries

Assets are tenant operational/load identity, RC/POD evidence, pickup and financial authority, accounts, audit evidence, Action Center accountability, and secrets/configuration. Trust crosses browser/client → authenticated API → tenant membership/capabilities → MongoDB and local document storage. Provider and AI/tool boundaries are future, untrusted boundaries.

## Actors and threats

Compromised or malicious tenant users, external attackers, stolen trucking identities, insiders, malicious uploaders, and future compromised integrations or prompt/tool inputs may attempt IDOR, tenant leakage, privilege escalation, credential theft, replay/stale authority, cargo-theft identity abuse, document injection, SSRF/path traversal, financial manipulation, duplicate invoicing, audit/reconciliation bypass, or sensitive-log/config leakage.

## Repository-grounded controls

| Threat | Current control |
|---|---|
| IDOR / tenant leakage | DB-backed tenant membership, tenant-scoped queries, privacy-preserving 404s, tenant identity indexes |
| Privilege escalation | Capability permissions and Action Center category/owner acknowledgement policy |
| Replay / stale authority | Pickup Release version/basis binding, Mutation Impact Planner invalidation, execution prerequisite checks |
| Cargo/party identity abuse | Explicit Party Verification and human clearance; acknowledgement never changes source authority |
| Document injection/traversal/SSRF | Phase 2E signature/MIME/size validation, server storage keys, immutable bytes/SHA-256, no arbitrary URL fetching |
| Financial manipulation / duplicate invoice | Invoice Readiness and canonical RC basis, Phase 2C authority rules, Phase 2B operation/idempotency, unique manifest, outbox/reconciliation |
| Audit tampering | Patch 0D append-only audit-first authoritative mutations and integrity verification |
| False-clean operations | Production Integrity, reconciliation, and fail-closed Action Center snapshot/CAS behavior |
| Sensitive logs/config | Observability redaction and secret-free readiness output |

## Residual risk

Real-Mongo index/concurrency and backup/restore require staging execution. Local storage is single-host and lacks malware scanning and production object-store durability. Action Center is request-refreshed with bounded source reads and first-50 UI results. SSO/SCIM and provider controls are deferred. Future AI introduces prompt injection/tool abuse; ADR-007 requires provenance and controlled human authority for material actions.
