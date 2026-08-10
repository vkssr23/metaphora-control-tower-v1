# ADR-003: Audit-first authoritative mutations

Status: Accepted

Context: Material freight authority must remain attributable.

Decision: Patch 0D audit evidence precedes authoritative mutation; failures do not return false success.

Consequences: Mutations can fail closed when audit persistence is unavailable.

Alternatives considered: Best-effort post-write logging was rejected.

Future review trigger: Transactional infrastructure can strengthen atomicity without weakening audit truth.
