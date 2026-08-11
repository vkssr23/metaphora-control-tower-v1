# ADR-005: Action Center is a projection

Status: Accepted

Context: Operators need one queue without competing source authority.

Decision: Action items project source truth. Acknowledgement records accountability; only source workflow correction resolves an item.

Consequences: Refresh completeness and CAS conflicts fail closed.

Alternatives considered: Manual resolution and a second workflow authority were rejected.

Future review trigger: Durable event-driven refresh is justified.
