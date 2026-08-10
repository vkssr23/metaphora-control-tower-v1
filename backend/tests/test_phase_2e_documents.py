import hashlib
from io import BytesIO
from dataclasses import replace
from pathlib import Path

import pytest
from app.api import document_routes

from app.application.document_service import storage_key_for, stored_metadata
from app.domain.document_evidence import (
    DocumentValidationError, safe_original_filename, validate_content,
)
from app.infrastructure.document_storage import DocumentObjectMissing, DocumentStorageError
from app.infrastructure.local_document_storage import LocalDocumentStorage
from test_mutation_endpoints import api, VALID_TENANT
import server
from app.config import Settings


PDF = b"%PDF-1.7\nopaque pilot evidence\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\nopaque"
JPEG = b"\xff\xd8\xff\xe0opaque"


@pytest.mark.parametrize("launch_directory", ["backend", "."])
def test_default_local_storage_root_is_precisely_gitignored(monkeypatch,launch_directory):
    repository=Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repository / launch_directory)
    monkeypatch.delenv("DOCUMENT_STORAGE_ROOT",raising=False)
    settings=Settings.from_env()
    resolved=(Path.cwd() / settings.document_storage_root).resolve()
    relative=resolved.relative_to(repository).as_posix()
    rules={line.strip() for line in (repository / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert f"/{relative}/" in rules
    assert rules.isdisjoint({"data/","/data/","backend/data/","/backend/data/"})


@pytest.mark.parametrize("raw,expected", [
    ("normal.pdf", "normal.pdf"),
    ("../../normal.pdf", "normal.pdf"),
    (r"C:\fake\normal.pdf", "normal.pdf"),
    ("document.pdf\r\nX-Evil: 1", "document.pdf__X-Evil: 1"),
])
def test_filename_is_display_safe(raw, expected):
    assert safe_original_filename(raw) == expected


def test_long_filename_is_bounded_and_keeps_extension():
    result=safe_original_filename("a" * 300 + ".pdf")
    assert len(result) == 180 and result.endswith(".pdf")


@pytest.mark.parametrize("mime,content", [
    ("application/pdf",PDF), ("image/png",PNG), ("image/jpeg",JPEG),
])
def test_supported_signatures(mime,content):
    assert validate_content(mime,content) == mime


@pytest.mark.parametrize("mime,content", [
    ("application/pdf",b"not a pdf"), ("image/png",JPEG),
    ("image/jpeg",PNG), ("text/html",b"<html>"), (None,PDF),
])
def test_mismatch_and_unsupported_content_is_rejected(mime,content):
    with pytest.raises(DocumentValidationError): validate_content(mime,content)


def test_metadata_hashes_actual_bytes_and_has_no_authenticity_claim():
    result=stored_metadata(tenant_id="ten_a",document_id="DOC1",filename="../../rc.pdf",
        content_type="application/pdf",content=PDF,provider="local_filesystem")
    assert result["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert result["size_bytes"] == len(PDF) and result["safe_filename"] == "rc.pdf"
    assert not ({"verified","authentic","accepted","extracted"} & result.keys())


def test_storage_keys_are_server_generated_and_filename_independent():
    one=storage_key_for("ten_a","DOC1"); two=storage_key_for("ten_a","DOC1")
    assert one != two and one.startswith("ten_a/DOC1/") and one.endswith(".blob")
    assert ".." not in one


def test_local_storage_is_immutable_exact_and_cleanup_is_specific(tmp_path):
    storage=LocalDocumentStorage(tmp_path); key="ten_a/DOC1/a.blob"
    storage.put(key,PDF)
    assert storage.exists(key) and storage.open(key).read() == PDF
    with pytest.raises(DocumentStorageError): storage.put(key,PNG)
    storage.delete_if_uncommitted(key)
    assert not storage.exists(key)


@pytest.mark.parametrize("key", ["../escape", "x/../../escape", r"x\escape", ""])
def test_local_storage_rejects_traversal_and_invalid_keys(tmp_path,key):
    storage=LocalDocumentStorage(tmp_path)
    with pytest.raises(DocumentStorageError): storage.put(key,PDF)


def test_missing_local_object_is_controlled(tmp_path):
    with pytest.raises(DocumentObjectMissing): LocalDocumentStorage(tmp_path).open("ten_a/DOC1/missing.blob")


def test_real_upload_metadata_duplicate_awareness_and_download(api,tmp_path,monkeypatch):
    client,db,role=api; role("operations"); db.loads.docs=[{"id":"L1","tenant_id":VALID_TENANT}]
    storage=LocalDocumentStorage(tmp_path); monkeypatch.setattr(document_routes,"get_document_storage",lambda:storage)
    files={"file":("../../bol.pdf",PDF,"application/pdf")}
    first=client.post("/api/documents/upload",data={"load_id":"L1","doc_type":"bol"},files=files)
    assert first.status_code==201,first.text
    body=first.json(); assert body["filename"]=="bol.pdf" and body["storage_status"]=="stored"
    assert body["sha256"]==hashlib.sha256(PDF).hexdigest() and body["duplicate_sha256"] is False
    assert "storage_key" not in body and storage.exists(db.documents.docs[-1]["storage_key"])
    download=client.get(f"/api/documents/{body['id']}/download")
    assert download.status_code==200 and download.content==PDF
    assert download.headers["x-content-type-options"]=="nosniff" and "bol.pdf" in download.headers["content-disposition"]
    second=client.post("/api/documents/upload",data={"load_id":"L1","doc_type":"bol"},files=files)
    assert second.status_code==201 and second.json()["duplicate_sha256"] is True
    assert second.json()["matching_document_ids"]==[body["id"]]


def test_upload_rejects_mismatch_without_storing(api,tmp_path,monkeypatch):
    client,db,role=api; role("operations"); db.loads.docs=[{"id":"L1","tenant_id":VALID_TENANT}]
    storage=LocalDocumentStorage(tmp_path); monkeypatch.setattr(document_routes,"get_document_storage",lambda:storage)
    response=client.post("/api/documents/upload",data={"load_id":"L1","doc_type":"bol"},
        files={"file":("fake.pdf",b"executable", "application/pdf")})
    assert response.status_code==422 and not db.documents.docs and not list(tmp_path.rglob("*.blob"))


def test_actual_bytes_enforce_size_limit_without_content_length_trust(api,tmp_path,monkeypatch):
    client,db,role=api; role("operations"); db.loads.docs=[{"id":"L1","tenant_id":VALID_TENANT}]
    storage=LocalDocumentStorage(tmp_path); monkeypatch.setattr(document_routes,"get_document_storage",lambda:storage)
    monkeypatch.setattr(server,"settings",replace(server.settings,document_max_upload_bytes=32))
    response=client.post("/api/documents/upload",data={"load_id":"L1","doc_type":"bol"},
        files={"file":("large.pdf",PDF + b"x" * 40,"application/pdf")},headers={"Content-Length":"1"})
    assert response.status_code==413 and not db.documents.docs and not list(tmp_path.rglob("*.blob"))


def test_legacy_mock_download_never_fabricates_bytes(api,tmp_path,monkeypatch):
    client,db,role=api; role("operations")
    db.documents.docs=[{"id":"OLD","tenant_id":VALID_TENANT,"load_id":"L1","doc_type":"pod","filename":"pod.pdf","url":"mock://pod.pdf"}]
    monkeypatch.setattr(document_routes,"get_document_storage",lambda:LocalDocumentStorage(tmp_path))
    response=client.get("/api/documents/OLD/download")
    assert response.status_code==409 and "legacy reference" in response.text


def test_download_is_tenant_authorized_even_when_document_id_is_known(api,tmp_path,monkeypatch):
    client,db,role=api; role("operations")
    storage=LocalDocumentStorage(tmp_path); key="ten_a/DOC1/a.blob"; storage.put(key,PDF)
    db.documents.docs=[{"id":"DOC1","tenant_id":VALID_TENANT,"load_id":"L1","doc_type":"pod",
        "filename":"pod.pdf","safe_filename":"pod.pdf","content_type":"application/pdf",
        "storage_provider":"local_filesystem","storage_key":key,"storage_status":"stored"}]
    monkeypatch.setattr(document_routes,"get_document_storage",lambda:storage)
    async def foreign(): return {"id":"U-B","role":"owner","tenant_id":"ten_" + "b" * 32}
    server.app.dependency_overrides[server.get_current_user]=foreign
    assert client.get("/api/documents/DOC1/download").status_code==404


def test_storage_write_failure_has_no_record_or_false_success(api,tmp_path,monkeypatch):
    client,db,role=api; role("operations"); db.loads.docs=[{"id":"L1","tenant_id":VALID_TENANT}]
    class FailingStorage(LocalDocumentStorage):
        def put(self,key,content): raise DocumentStorageError("private path must be redacted")
    monkeypatch.setattr(document_routes,"get_document_storage",lambda:FailingStorage(tmp_path))
    response=client.post("/api/documents/upload",data={"load_id":"L1","doc_type":"bol"},
        files={"file":("bol.pdf",PDF,"application/pdf")})
    assert response.status_code==503 and not db.documents.docs and "private path" not in response.text


def test_db_insert_failure_cleans_exact_uncommitted_object(api,tmp_path,monkeypatch):
    client,db,role=api; role("operations"); db.loads.docs=[{"id":"L1","tenant_id":VALID_TENANT}]
    storage=LocalDocumentStorage(tmp_path); monkeypatch.setattr(document_routes,"get_document_storage",lambda:storage)
    async def fail_insert(doc): raise RuntimeError("database unavailable")
    monkeypatch.setattr(db.documents,"insert_one",fail_insert)
    response=client.post("/api/documents/upload",data={"load_id":"L1","doc_type":"bol"},
        files={"file":("bol.pdf",PDF,"application/pdf")})
    assert response.status_code==500 and not list(tmp_path.rglob("*.blob"))


def test_cleanup_failure_is_not_reported_as_success(api,tmp_path,monkeypatch,caplog):
    client,db,role=api; role("operations"); db.loads.docs=[{"id":"L1","tenant_id":VALID_TENANT}]
    class CleanupFailStorage(LocalDocumentStorage):
        def delete_if_uncommitted(self,key): raise DocumentStorageError("cleanup failed")
    storage=CleanupFailStorage(tmp_path); monkeypatch.setattr(document_routes,"get_document_storage",lambda:storage)
    async def fail_insert(doc): raise RuntimeError("database unavailable")
    monkeypatch.setattr(db.documents,"insert_one",fail_insert)
    response=client.post("/api/documents/upload",data={"load_id":"L1","doc_type":"bol"},
        files={"file":("bol.pdf",PDF,"application/pdf")})
    assert response.status_code==500 and list(tmp_path.rglob("*.blob"))
    assert "Uncommitted document cleanup failed" in caplog.text
