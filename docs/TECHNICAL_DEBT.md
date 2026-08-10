# Technical Debt Register

| ID | Area | Severity | Risk | Identified | Reason deferred | Target/trigger | Status |
|---|---|---|---|---|---|---|---|
| TD-001 | Mongo | P1 | Real partial-index and concurrency behavior unverified here | 2G | No disposable Mongo supplied | Before customer pilot | Open |
| TD-002 | Indexes | P1 | Manifest not applied to staging | 2A/2G | Production access prohibited | Staging provisioning | Open |
| TD-003 | Documents | P1 | Local storage lacks multi-host durability and malware scan | 2E | Provider integration deferred | Before broader production | Open |
| TD-004 | Documents | P2 | Orphan object inventory is manual | 2E | Narrow pilot scope | Object-store adapter | Open |
| TD-005 | Action Center | P2 | Request-driven refresh, 5,000/source boundary, first 50 UI results | 2F | Pilot bound accepted | Queue volume exceeds bounds | Open |
| TD-006 | Recovery | P1 | Full backup/restore drill unexecuted | 2G | No disposable staging DB | Before customer data | Open |
| TD-007 | Identity | P2 | SSO/SCIM deferred | 2G | Not needed for controlled pilot | Enterprise identity demand | Deferred |
