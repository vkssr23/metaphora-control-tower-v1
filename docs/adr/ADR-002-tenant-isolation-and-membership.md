# ADR-002: Tenant isolation and membership

Status: Accepted

Context: Freight and evidence data is confidential between carriers.

Decision: DB membership is authoritative; every operational lookup and identity is tenant scoped, with non-leaking denial semantics.

Consequences: Tenant context is mandatory throughout workflows and indexes.

Alternatives considered: Client-provided tenant trust and globally exposed IDs were rejected.

Future review trigger: A separately reviewed cross-tenant collaboration product is introduced.
