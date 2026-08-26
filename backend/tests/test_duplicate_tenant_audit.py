"""Proves the duplicate-tenant audit is read-only, bounded, and never leaks
the org id, tenant name, or any document payload."""
import ast
import asyncio
import hashlib
import json
from pathlib import Path

from pymongo.errors import ExecutionTimeout

from app.production_integrity import TENANT_SCOPED
from scripts import duplicate_tenant_audit as audit

WRITE_METHODS = {
    "insert_one", "insert_many", "update_one", "update_many", "delete_one",
    "delete_many", "create_index", "create_indexes", "drop_index",
    "drop_indexes", "drop", "replace_one", "find_one_and_update",
    "find_one_and_delete", "find_one_and_replace", "bulk_write", "rename",
    "drop_database",
}

ORG_ID = "42"  # the value that must never appear in output, only its hash
TENANT_A, TENANT_B = "ten_" + "a" * 32, "ten_" + "b" * 32


class ForbiddenCall(AssertionError):
    pass


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return list(self._docs)


class FakeCollection:
    def __init__(self, name, calls, tenants_by_id, related_counts, timeout_on):
        self._name, self._calls = name, calls
        self._tenants_by_id, self._related_counts, self._timeout_on = tenants_by_id, related_counts, timeout_on

    def aggregate(self, pipeline, maxTimeMS=None):
        self._calls.append(("aggregate", self._name, maxTimeMS))
        if "aggregate" in self._timeout_on:
            raise ExecutionTimeout("simulated timeout")
        group = [{"_id": ORG_ID, "ids": [TENANT_A, TENANT_B], "n": 2}] if self._tenants_by_id else []
        return FakeCursor(group)

    async def find_one(self, filt, projection=None, *, max_time_ms=None):
        # Deliberately strict, no **kwargs catch-all: real pymongo find()/
        # find_one() build a Cursor whose __init__ has an explicit parameter
        # list (max_time_ms, snake_case) and no catch-all either — passing
        # the camelCase maxTimeMS used by aggregate()/count_documents()/
        # command() here must raise TypeError, exactly like the real driver.
        self._calls.append(("find_one", self._name, max_time_ms))
        if "find_one" in self._timeout_on:
            raise ExecutionTimeout("simulated timeout")
        return self._tenants_by_id.get(filt.get("id"))

    async def count_documents(self, filt, maxTimeMS=None):
        self._calls.append(("count_documents", self._name, maxTimeMS))
        if "count_documents" in self._timeout_on:
            raise ExecutionTimeout("simulated timeout")
        return self._related_counts.get((self._name, filt.get("tenant_id")), 0)

    def __getattr__(self, item):
        if item in WRITE_METHODS:
            raise ForbiddenCall(f"write method on collection: {item}")
        raise AttributeError(item)


class FakeDB:
    def __init__(self, calls, tenants_by_id, related_counts, timeout_on):
        self._calls, self._tenants_by_id = calls, tenants_by_id
        self._related_counts, self._timeout_on = related_counts, timeout_on

    def __getitem__(self, name):
        return FakeCollection(name, self._calls, self._tenants_by_id if name == "tenants" else {}, self._related_counts, self._timeout_on)

    def __getattr__(self, item):
        # Real motor Database objects resolve db.name the same as db["name"]
        # (both are collection accessors); mirror that here.
        if item in WRITE_METHODS:
            raise ForbiddenCall(f"write method on db: {item}")
        return self[item]


class FakeClient:
    def __init__(self, tenants_by_id=None, related_counts=None, timeout_on=None):
        self.calls = []
        self._db = FakeDB(self.calls, tenants_by_id or {}, related_counts or {}, timeout_on or set())
        self.closed = False

    def __getitem__(self, _name):
        return self._db

    def close(self):
        self.closed = True

    def __getattr__(self, item):
        if item in WRITE_METHODS:
            raise ForbiddenCall(f"write method on client: {item}")
        raise AttributeError(item)


def _standard_fixture():
    tenants_by_id = {
        TENANT_A: {"id": TENANT_A, "status": "active", "created_at": "2026-01-01T00:00:00Z", "name": "Acme Freight", "metaphora_org_id": ORG_ID},
        TENANT_B: {"id": TENANT_B, "status": "active", "created_at": "2026-02-01T00:00:00Z", "name": "smoke-test-org", "metaphora_org_id": ORG_ID},
    }
    related_counts = {("users", TENANT_A): 3, ("users", TENANT_B): 0, ("loads", TENANT_A): 5}
    return tenants_by_id, related_counts


def test_org_id_is_fingerprinted_never_printed_raw():
    tenants_by_id, related_counts = _standard_fixture()
    client = FakeClient(tenants_by_id, related_counts)
    report = asyncio.run(audit.run_audit("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "CONFLICT_AUDITED"
    dumped = json.dumps(report)
    assert ORG_ID not in dumped
    assert "Acme Freight" not in dumped and "smoke-test-org" not in dumped
    assert report["org_id_fingerprint_sha256"] == hashlib.sha256(ORG_ID.encode()).hexdigest()


def test_both_tenant_ids_and_required_metadata_reported():
    tenants_by_id, related_counts = _standard_fixture()
    client = FakeClient(tenants_by_id, related_counts)
    report = asyncio.run(audit.run_audit("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    ids = {t["tenant_id"] for t in report["tenants"]}
    assert ids == {TENANT_A, TENANT_B}
    for t in report["tenants"]:
        assert set(t.keys()) == {
            "tenant_id", "created_at", "status", "is_known_smoke_tenant",
            "metaphora_org_id_shape", "user_count", "related_record_counts",
        }
        shape = t["metaphora_org_id_shape"]
        assert set(shape.keys()) == {"exists", "bson_type", "is_null", "is_empty_or_whitespace", "string_length"}
        assert shape["exists"] is True and shape["bson_type"] == "string" and shape["is_null"] is False


def test_org_id_shape_missing_field():
    shape = audit._org_id_shape({"id": TENANT_A})
    assert shape == {"exists": False, "bson_type": "missing", "is_null": False, "is_empty_or_whitespace": False, "string_length": None}


def test_org_id_shape_explicit_null():
    shape = audit._org_id_shape({"id": TENANT_A, "metaphora_org_id": None})
    assert shape == {"exists": True, "bson_type": "null", "is_null": True, "is_empty_or_whitespace": False, "string_length": None}


def test_org_id_shape_empty_string():
    shape = audit._org_id_shape({"id": TENANT_A, "metaphora_org_id": ""})
    assert shape["exists"] is True and shape["bson_type"] == "string" and shape["is_null"] is False
    assert shape["is_empty_or_whitespace"] is True and shape["string_length"] == 0


def test_org_id_shape_whitespace_only_string():
    shape = audit._org_id_shape({"id": TENANT_A, "metaphora_org_id": "   "})
    assert shape["bson_type"] == "string" and shape["is_empty_or_whitespace"] is True and shape["string_length"] == 3


def test_org_id_shape_valid_id_never_exposes_the_value():
    shape = audit._org_id_shape({"id": TENANT_A, "metaphora_org_id": "42"})
    assert shape["exists"] is True and shape["bson_type"] == "string"
    assert shape["is_null"] is False and shape["is_empty_or_whitespace"] is False
    assert shape["string_length"] == 2
    assert "42" not in json.dumps(shape)


def test_smoke_tenant_name_heuristic_is_boolean_only():
    tenants_by_id, related_counts = _standard_fixture()
    client = FakeClient(tenants_by_id, related_counts)
    report = asyncio.run(audit.run_audit("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    by_id = {t["tenant_id"]: t for t in report["tenants"]}
    assert by_id[TENANT_A]["is_known_smoke_tenant"] is False
    assert by_id[TENANT_B]["is_known_smoke_tenant"] is True


def test_related_record_counts_cover_every_tenant_scoped_collection():
    tenants_by_id, related_counts = _standard_fixture()
    client = FakeClient(tenants_by_id, related_counts)
    report = asyncio.run(audit.run_audit("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    for t in report["tenants"]:
        assert set(t["related_record_counts"].keys()) == TENANT_SCOPED
    a = next(t for t in report["tenants"] if t["tenant_id"] == TENANT_A)
    assert a["related_record_counts"]["users"] == 3 and a["user_count"] == 3
    assert a["related_record_counts"]["loads"] == 5


def test_reassignment_fields_enumerate_tenant_id_and_scoped_collections():
    tenants_by_id, related_counts = _standard_fixture()
    client = FakeClient(tenants_by_id, related_counts)
    report = asyncio.run(audit.run_audit("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    rf = report["reassignment_fields"]
    assert rf["per_tenant_scoped_collection_field"] == "tenant_id"
    assert set(rf["tenant_scoped_collections"]) == TENANT_SCOPED
    assert rf["sso_link_field_on_tenants"] == "metaphora_org_id"


def test_find_one_uses_max_time_ms_not_camelcase_and_succeeds():
    """Regression for the production TypeError: find()/find_one() route into
    pymongo's Cursor, whose __init__ has an explicit parameter list
    (max_time_ms) and no **kwargs catch-all — unlike aggregate()/
    count_documents()/command(). The strict FakeCollection.find_one above
    would raise TypeError on the old maxTimeMS= call; a clean CONFLICT_AUDITED
    result here proves the fixed call matches the real driver's contract."""
    tenants_by_id, related_counts = _standard_fixture()
    client = FakeClient(tenants_by_id, related_counts)
    report = asyncio.run(audit.run_audit("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "CONFLICT_AUDITED"
    find_one_calls = [c for c in client.calls if c[0] == "find_one"]
    assert find_one_calls and all(c[2] is not None for c in find_one_calls)


def test_old_camelcase_kwarg_would_fail_against_the_real_driver_contract():
    """Fails under the previously-shipped call pattern: proves the fake's
    find_one has no **kwargs catch-all, so maxTimeMS= (the old bug) raises
    TypeError exactly as the real pymongo Cursor does."""
    tenants_by_id, related_counts = _standard_fixture()
    client = FakeClient(tenants_by_id, related_counts)
    collection = client["db"].tenants
    try:
        asyncio.run(collection.find_one({"id": TENANT_A}, {"_id": 0}, maxTimeMS=4000))
        raise AssertionError("expected TypeError for unexpected keyword argument 'maxTimeMS'")
    except TypeError:
        pass


def test_no_conflict_group_reports_clean_status():
    client = FakeClient(tenants_by_id={}, related_counts={})
    report = asyncio.run(audit.run_audit("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "NO_CONFLICT_FOUND"


def test_timeout_on_group_discovery_fails_closed():
    client = FakeClient(timeout_on={"aggregate"})
    report = asyncio.run(audit.run_audit("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "INCOMPLETE_UNSAFE"
    assert report["status"] not in {"CONFLICT_AUDITED", "NO_CONFLICT_FOUND"}


def test_timeout_on_related_count_fails_closed():
    tenants_by_id, related_counts = _standard_fixture()
    client = FakeClient(tenants_by_id, related_counts, timeout_on={"count_documents"})
    report = asyncio.run(audit.run_audit("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "INCOMPLETE_UNSAFE"


def test_missing_env_fails_closed_without_connecting():
    def forbidden(_uri, **_kw):
        raise AssertionError("should never construct a client without MONGO_URL/DB_NAME")
    code = audit.main(environ={}, client_factory=forbidden)
    assert code == 2


def test_safe_diagnostic_contains_only_file_function_line():
    try:
        raise ValueError("a secret-looking value that must never be echoed: sk_live_12345")
    except ValueError as exc:
        diag = audit._safe_diagnostic(exc)
    assert set(diag.keys()) == {"file", "function", "line"}
    assert diag["function"] == "test_safe_diagnostic_contains_only_file_function_line"
    assert isinstance(diag["line"], int)
    dumped = json.dumps(diag)
    assert "sk_live_12345" not in dumped and "secret-looking" not in dumped


def test_main_error_path_never_prints_exception_message(capsys):
    def raises_with_secret(_uri, **_kw):
        raise TypeError("unexpected keyword argument 'maxTimeMS' near mongodb://user:hunter2@host/db")
    code = audit.main(environ={"MONGO_URL": "mongodb://fake", "DB_NAME": "db"}, client_factory=raises_with_secret)
    out = capsys.readouterr().out
    assert code == 2
    assert "hunter2" not in out and "maxTimeMS" not in out
    parsed = json.loads(out)
    assert parsed["reason_code"] == "TypeError"
    assert set(parsed["diagnostic"].keys()) == {"file", "function", "line"}


def _called_names(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                yield func.attr
            elif isinstance(func, ast.Name):
                yield func.id


def test_module_source_contains_no_write_capable_calls():
    tree = ast.parse(Path(audit.__file__).read_text())
    hits = sorted(set(_called_names(tree)) & WRITE_METHODS)
    assert hits == [], f"write-capable call(s) found: {hits}"
