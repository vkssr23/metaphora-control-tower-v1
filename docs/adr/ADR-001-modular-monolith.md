# ADR-001: Modular monolith

Status: Accepted

Context: Freight authority workflows share transactional and audit concerns.

Decision: Keep one deployable backend with domain, application, infrastructure, schema, and API boundaries.

Consequences: Simple operations and explicit imports; modules still require discipline.

Alternatives considered: Microservices were rejected without scale/team boundaries.

Future review trigger: Independent scaling, ownership, or isolation requirements are measured.
