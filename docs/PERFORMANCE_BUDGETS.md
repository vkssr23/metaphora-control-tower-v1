# Pilot Performance Budgets

These are targets, not measured promises: normal reads p95 ≤500 ms; normal mutations p95 ≤1 s; Action Center list p95 ≤1 s; refresh p95 ≤3 s within its 5,000-record-per-source completeness boundary; document upload ≤15 MiB and p95 ≤5 s; document download first byte p95 ≤2 s; invoice creation p95 ≤3 s; offline Golden Flow ≤60 s. The Action Center UI currently returns the first 50 results and refresh is request-driven, not real-time. Load testing is a future staging gate.
