# ADR-006: Transaction, outbox, and reconciliation model

Status: Accepted

Context: Invoice creation spans authority, package, invoice, event, and operation state.

Decision: Use idempotent operation identities, transaction capability when available, outbox evidence, and explicit reconciliation for uncertain partial state.

Consequences: Exactly-once external side effects are not claimed.

Alternatives considered: Untracked multi-write success and direct provider calls were rejected.

Future review trigger: Measured throughput or provider requirements exceed this model.
