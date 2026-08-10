"""Application helpers for bounded upload preparation."""
from __future__ import annotations

import uuid

from app.domain.document_evidence import content_sha256, safe_original_filename, validate_content


def storage_key_for(tenant_id: str, document_id: str) -> str:
    # Tenant/document values are server authorities; the random leaf prevents
    # accidental overwrite and never incorporates a client filename.
    safe_tenant = "".join(c for c in tenant_id if c.isalnum() or c in "_-")[:80]
    safe_document = "".join(c for c in document_id if c.isalnum() or c in "_-")[:80]
    if not safe_tenant or not safe_document:
        raise ValueError("Invalid document storage identity")
    return f"{safe_tenant}/{safe_document}/{uuid.uuid4().hex}.blob"


def stored_metadata(*, tenant_id: str, document_id: str, filename: str | None,
                    content_type: str | None, content: bytes, provider: str) -> dict:
    mime = validate_content(content_type, content)
    safe_name = safe_original_filename(filename)
    return {
        "filename": safe_name,
        "original_filename": safe_name,
        "safe_filename": safe_name,
        "content_type": mime,
        "size_bytes": len(content),
        "sha256": content_sha256(content),
        "storage_provider": provider,
        "storage_key": storage_key_for(tenant_id, document_id),
        "storage_status": "stored",
        "source_type": "manual_upload",
        "version": 1,
    }
