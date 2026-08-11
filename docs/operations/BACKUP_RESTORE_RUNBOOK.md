# Backup and Restore Runbook

Status: DOCUMENTED_NOT_EXECUTED.

Back up Mongo with an approved encrypted staging mechanism, immutable local/object document bytes, and separately managed configuration/secrets. Never place secrets in the backup manifest. Preserve audit events with the data snapshot. Restore in order: configuration references, Mongo, documents, then application. Validate tenant counts and isolation, audit integrity, document SHA-256/object presence, integrity scan, indexes, Golden Flow, invoice/outbox/reconciliation consistency, and Action Center refresh. Targets are RPO 24 hours and RTO 8 hours; neither is measured. A disposable staging drill is required before customer data.
