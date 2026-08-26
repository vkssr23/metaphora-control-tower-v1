"""Proves scripts/check_mongo_indexes.py is structurally read-only and correct.

A fake Motor client/db/collection raises on any write-capable method name
(insert/update/delete/create_index/drop*/...) rather than silently no-op'ing
it, so if the script under test ever called one, these tests would fail
loudly instead of passing by accident.
"""
import asyncio
from pathlib import Path

from app.infrastructure.index_manifest import expected_indexes
from scripts import check_mongo_indexes as checker

WRITE_METHODS = {
    "insert_one", "insert_many", "update_one", "update_many", "delete_one",
    "delete_many", "create_index", "create_indexes", "drop_index",
    "drop_indexes", "drop", "replace_one", "find_one_and_update",
    "find_one_and_delete", "find_one_and_replace", "bulk_write", "rename",
    "drop_database",
}


class ForbiddenCall(AssertionError):
    pass


class FakeCursor:
    def __init__(self, specs):
        self._specs = specs

    async def to_list(self, length=None):
        return list(self._specs)


class FakeCollection:
    def __init__(self, name, specs, calls):
        self._name, self._specs, self._calls = name, specs, calls

    def list_indexes(self):
        self._calls.append(("list_indexes", self._name))
        return FakeCursor(self._specs)

    def __getattr__(self, item):
        if item in WRITE_METHODS:
            raise ForbiddenCall(f"write method called on collection: {item}")
        raise AttributeError(item)


class FakeDB:
    def __init__(self, collections, calls):
        self._collections, self._calls = collections, calls

    async def list_collection_names(self):
        self._calls.append(("list_collection_names",))
        return list(self._collections.keys())

    def __getitem__(self, name):
        return FakeCollection(name, self._collections.get(name, []), self._calls)

    def __getattr__(self, item):
        if item in WRITE_METHODS:
            raise ForbiddenCall(f"write method called on db: {item}")
        raise AttributeError(item)


class FakeClient:
    def __init__(self, collections):
        self.calls = []
        self._db = FakeDB(collections, self.calls)
        self.closed = False

    def __getitem__(self, _name):
        return self._db

    def close(self):
        self.closed = True

    def __getattr__(self, item):
        if item in WRITE_METHODS:
            raise ForbiddenCall(f"write method called on client: {item}")
        raise AttributeError(item)


def factory(collections):
    def _f(uri, **kwargs):
        return FakeClient(collections)
    return _f


def _manifest_as_observed():
    """Fake DB contents that exactly satisfy the manifest."""
    out = {}
    for idx in expected_indexes():
        out.setdefault(idx.collection, []).append({
            "name": idx.name, "key": dict(idx.fields), "unique": idx.unique,
            "partialFilterExpression": idx.partial_filter,
        })
    return out


def test_matching_manifest_passes_and_calls_only_read_methods():
    client = FakeClient(_manifest_as_observed())
    report = asyncio.run(checker.inspect_indexes("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "PASS"
    assert report["missing"] == [] and report["mismatched"] == []
    assert client.closed
    assert all(call[0] in {"list_collection_names", "list_indexes"} for call in client.calls)
    assert ("list_indexes", "tenants") in client.calls


def test_missing_collection_is_not_created_and_reported_missing():
    observed = _manifest_as_observed()
    del observed["tenants"]  # collection absent entirely
    client = FakeClient(observed)
    report = asyncio.run(checker.inspect_indexes("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "DRIFT"
    assert any(m["collection"] == "tenants" and m["name"] == "uq_tenants_metaphora_org_id" for m in report["missing"])


def test_drifted_index_definition_is_detected():
    observed = _manifest_as_observed()
    for spec in observed["tenants"]:
        if spec["name"] == "uq_tenants_metaphora_org_id":
            spec["unique"] = False  # drift: declared unique, observed not
    client = FakeClient(observed)
    report = asyncio.run(checker.inspect_indexes("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "DRIFT"
    assert {"collection": "tenants", "name": "uq_tenants_metaphora_org_id"} in report["mismatched"]


def test_output_never_contains_connection_string_or_db_name(capsys):
    client = FakeClient(_manifest_as_observed())
    secret_uri = "mongodb://user:sup3rsecret@prod-host/proddb"
    code = checker.main(
        environ={"MONGO_URL": secret_uri, "DB_NAME": "proddb-real-name"},
        client_factory=lambda uri, **kw: client,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert secret_uri not in out
    assert "sup3rsecret" not in out
    assert "proddb-real-name" not in out


def test_missing_env_fails_closed_without_connecting():
    def forbidden(_uri, **_kw):
        raise AssertionError("should never construct a client without MONGO_URL/DB_NAME")
    code = checker.main(environ={}, client_factory=forbidden)
    assert code == 2


def test_tenant_org_id_index_definition_matches_sso_idempotency_requirement():
    idx = next(x for x in expected_indexes() if x.name == "uq_tenants_metaphora_org_id")
    assert idx.collection == "tenants"
    assert idx.unique is True
    assert idx.fields == (("metaphora_org_id", 1),)
    # $exists:True alone also matches an explicit null (what every ordinary,
    # non-SSO tenant used to write) — corrected to $type:"string" + $gt:"" so
    # only real linked-org strings participate in the unique constraint.
    assert idx.partial_filter == {"metaphora_org_id": {"$type": "string", "$gt": ""}}


def test_module_source_contains_no_write_capable_calls():
    source = Path(checker.__file__).read_text()
    forbidden_substrings = [f"{m}(" for m in WRITE_METHODS] + [".drop_database("]
    hits = [s for s in forbidden_substrings if s in source]
    assert hits == [], f"write-capable call(s) found in checker source: {hits}"
