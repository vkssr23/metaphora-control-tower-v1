# Phase 2E — Real Document Foundation

## Purpose and trust model

Phase 2E adds controlled storage of actual freight-document bytes for local,
test, and deliberately configured single-instance staging use. A stored object
means bytes are present and its SHA-256 identifies those bytes. It does **not**
mean the document is authentic, malware-free, parsed/extracted, accepted, or
that a party is verified. Those concepts remain separate existing or future
workflows.

## Supported evidence

The canonical document vocabulary remains `rate_con`, `bol`, `pod`, `lumper`,
`scale`, `invoice`, `other`, and `insurance`. The upload API accepts only PDF,
JPEG, and PNG (`application/pdf`, `image/jpeg`, `image/png`). It validates the
declared MIME against lightweight magic bytes and stores the file as opaque
bytes. The default limit is 15 MiB, configurable with
`DOCUMENT_MAX_UPLOAD_BYTES` (1 KiB–100 MiB); enforcement counts bytes read and
does not trust `Content-Length`.

## Architecture and configuration

- `domain/document_evidence.py`: bounded filename, MIME/signature, size default,
  and SHA-256 rules; no FastAPI or filesystem dependency.
- `infrastructure/document_storage.py`: narrow immutable `put`, `open`, `exists`,
  and proven-uncommitted cleanup boundary.
- `infrastructure/local_document_storage.py`: local adapter with containment
  checks and temporary-write/atomic-hard-link publication. Publication refuses
  an existing destination object and never replaces its bytes.
- `application/document_service.py`: server-generated key and stored metadata.
- `api/document_routes.py`: multipart/download adapters and reuse of the existing
  Phase 2C document mutation path.

Configuration uses the existing `Settings`: `DOCUMENT_STORAGE_BACKEND=local`,
`DOCUMENT_STORAGE_ROOT=./data/documents`, and a 15 MiB default
`DOCUMENT_MAX_UPLOAD_BYTES`. No cloud SDK or provider adapter was added.

Storage keys are generated as bounded tenant/document/random-object components.
Uploaded filenames never select a path. Display names strip POSIX/Windows path
components, replace controls, normalize whitespace, and are capped at 180
characters. Download uses the document record and authenticated tenant, never a
raw storage key, and returns controlled MIME, attachment filename, and
`X-Content-Type-Options: nosniff` without exposing filesystem paths.

## Records, identity, duplicates, and history

The existing `documents` collection remains authoritative. Real uploads add
`original_filename`, `safe_filename`, `content_type`, `size_bytes`, lowercase
SHA-256, `storage_provider`, `storage_key`, `storage_status`, `source_type`,
`version`, authenticated creator, and timestamps. SHA-256 is not a document ID
or authenticity proof. Duplicate lookup is tenant-scoped and non-unique; a new
document identity and object are retained while up to ten same-tenant matching
IDs are reported. Cross-tenant matches are neither queried nor disclosed.

Original bytes cannot be overwritten through the storage adapter or API. There
is no file-replacement or delete endpoint. Corrected RCs, PODs, receipts, or
insurance evidence therefore use a new document identity; existing workflow
revision/supersession rules continue to govern structured authorities and old
evidence remains available.

## Upload and failure sequence

Actual order:

1. authenticate/authorize; validate tenant-bound load;
2. read with the byte limit; validate type/signature; generate metadata/hash;
3. tenant-scoped duplicate lookup;
4. append upload-start audit;
5. write the immutable storage object;
6. invoke the existing document-create path, including its audit-first Phase 2C
   planner consequences and document insertion;
7. append terminal upload audit and return 201.

Validation or audit-start failure stores nothing. Storage failure creates no
record and returns no success. If DB insertion fails after storage, the exact
new unreferenced key is cleaned up. If that cleanup also fails before a document
record exists, the request still fails, the uniquely named orphan blob is
retained, and a bounded error is logged. There is no durable application
reconciliation record for this pre-record orphan; storage inventory/manual
orphan reconciliation remains a future hardening item. If a record is found
after a later failure, the file and record are preserved, `storage_status`
becomes `storage_reconciliation_required`, and the API fails with a controlled
503. This avoids expanding the Phase 2B operation registry into blob
infrastructure.

## Workflow behavior

Uploads use the same Mutation Impact Planner path as legacy document creation;
there is no second dependency graph. A stored `rate_con` is eligible for the
existing manual/structured extraction workflow but is not extracted or
accepted automatically. POD presence can participate in existing invoice
readiness evaluation but does not approve readiness or create/submit an
invoice. A lumper receipt does not approve an accessorial or change billing.
Insurance evidence triggers existing safety/pickup consequences but does not
verify coverage.

## Legacy and production integrity

The JSON `POST /api/documents` contract remains for compatibility and labels
new records as `legacy_reference`. Metadata remains readable. Downloading a
legacy `mock://` record returns a controlled conflict and never fabricates
bytes. Integrity scanning distinguishes real storage metadata, validates its
bounded fields, and continues to flag simulated references. The index manifest
adds a non-unique `(tenant_id, sha256)` lookup index; it is declarative only and
was not applied.

Local filesystem storage is not production-certified shared durability. Before
multi-instance production use, configure private object storage, encryption and
access policies, lifecycle/backup/versioning, malware scanning, provider
reconciliation, and (if desired) short-lived signed delivery. Phase 2E did not
implement OCR, AI extraction, PDF parsing, antivirus, authenticity verification,
email/Drive/Dropbox ingestion, external object storage, migrations, index
application, or deployment. A full real-document end-to-end lifecycle fixture
is deferred because the existing lifecycle requires extensive independent
human acceptance/clearance fixtures; Phase 2E instead preserves and regression
tests those established workflow boundaries.
