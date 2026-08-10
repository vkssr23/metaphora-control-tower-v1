# Metaphora Enterprise Engineering Principles

Current wedge: **Carrier Freight Execution & Control Tower** for operations/dispatch, safety, finance, fleet, management, and drivers where applicable. Brokers, shippers, and facilities participate but are not complete customer suites.

We enforce tenant isolation, deterministic authority, evidence provenance, audit-first material mutation, explicit reliability/outbox/reconciliation, observability, and tests before claims. We stay a modular monolith until measured team, scaling, or domain boundaries justify services. Integrations use adapters. Architecture is cost-aware and rejects fake enterprise features.

Complexity is trigger-based: microservices require ownership/scale boundaries; Kafka requires event needs beyond the outbox; Redis requires a proven cache/lock/job need; vector databases require retrieval workloads; knowledge graphs require graph queries; Kubernetes requires deployment/scale evidence.

Future AI may prepare or recommend, with provenance and evaluation. Material external, safety, financial, or irreversible action remains under controlled authority. Phase 2H is the first-real-integration boundary (potentially FMCSA, routing/maps, telematics, communications). A later Phase 3 may build an Agent Tool & Approval Plane. Neither is part of Phase 2G.

Data classes: Public (published product docs), Internal (engineering/operational metadata), Confidential (RC, POD, customer and load records), Highly Sensitive (credentials, signing secrets). Access, logs, and backups follow the highest class present.
