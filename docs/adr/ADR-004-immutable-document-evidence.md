# ADR-004: Immutable document evidence

Status: Accepted

Context: RC and POD bytes become authority inputs.

Decision: Store validated immutable bytes under server keys with SHA-256 and scoped metadata; uploads make no authenticity claim.

Consequences: Corrections create new evidence; cleanup failures remain visible.

Alternatives considered: Arbitrary URLs and overwrite-in-place were rejected.

Future review trigger: A production object-store adapter and malware scanning are approved.
