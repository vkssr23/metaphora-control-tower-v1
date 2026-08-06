# Security Patch 0B Mutation Guarantees

- An invoice's `load_id` is accepted at creation and immutable afterward.
- Entity updates inspect MongoDB `matched_count`; a pre-read cannot produce a false success after concurrent deletion.
- Load-stage writes use conditional predicates containing the observed stage. Exception recovery additionally matches the observed `exception_origin_stage`, and can return only to that origin.
- Activity records are currently best-effort after a successful stage or document write. An activity failure is logged with a fixed sanitized warning and does not falsely report that the primary write failed.
- A future transactional outbox or append-only audit ledger must replace this temporary degraded-audit policy.
- Driver compliance values are safety-managed administrative statuses, not evidence of external verification.
- Frontend dependencies are reproducibly locked by `frontend/yarn.lock`.
