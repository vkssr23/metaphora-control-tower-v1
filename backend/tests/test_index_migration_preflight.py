"""Proves the index migration preflight is structurally read-only and correct."""
import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from pymongo.errors import ExecutionTimeout

from app.infrastructure.index_manifest import expected_indexes
from scripts import index_migration_preflight as preflight
from scripts import apply_index_migration as apply_tool

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
    def __init__(self, docs):
        self._docs = docs

    def __getattr__(self, item):
        if item in WRITE_METHODS:
            raise ForbiddenCall(item)
        raise AttributeError(item)

    async def to_list(self, length=None):
        return list(self._docs)


class FakeCollection:
    def __init__(self, name, calls, count=0, conflicts=None, array_fields=None, timeout_on=None):
        self._name, self._calls, self._count = name, calls, count
        self._conflicts = conflicts or 0
        self._array_fields = array_fields or set()
        self._timeout_on = timeout_on or set()  # set of op names to raise ExecutionTimeout on

    async def estimated_document_count(self, maxTimeMS=None):
        self._calls.append(("estimated_document_count", self._name, maxTimeMS))
        if "estimated_document_count" in self._timeout_on:
            raise ExecutionTimeout("simulated timeout")
        return self._count

    def aggregate(self, pipeline, maxTimeMS=None):
        self._calls.append(("aggregate", self._name, maxTimeMS))
        if "aggregate" in self._timeout_on:
            raise ExecutionTimeout("simulated timeout")
        return FakeCursor([{"conflicts": self._conflicts}] if self._conflicts else [])

    async def count_documents(self, filt, limit=None, maxTimeMS=None):
        self._calls.append(("count_documents", self._name, maxTimeMS))
        if "count_documents" in self._timeout_on:
            raise ExecutionTimeout("simulated timeout")
        field = next(iter(filt))
        return 1 if field in self._array_fields else 0

    def __getattr__(self, item):
        if item in WRITE_METHODS:
            raise ForbiddenCall(f"write method on collection: {item}")
        raise AttributeError(item)


class FakeDB:
    def __init__(self, collections, calls, conflicts, array_fields, timeout_on):
        self._collections, self._calls, self._conflicts = collections, calls, conflicts
        self._array_fields, self._timeout_on = array_fields, timeout_on

    async def list_collection_names(self):
        self._calls.append(("list_collection_names",))
        return list(self._collections.keys())

    async def command(self, name, target=None, maxTimeMS=None):
        self._calls.append(("command", name, target, maxTimeMS))
        assert name == "collStats"
        if "command" in self._timeout_on:
            raise ExecutionTimeout("simulated timeout")
        return {"storageSize": 1024, "avgObjSize": 100}

    def __getitem__(self, name):
        return FakeCollection(
            name, self._calls, self._collections.get(name, 0), self._conflicts.get(name),
            self._array_fields.get(name), self._timeout_on,
        )

    def __getattr__(self, item):
        if item in WRITE_METHODS:
            raise ForbiddenCall(f"write method on db: {item}")
        raise AttributeError(item)


class FakeClient:
    def __init__(self, collections, conflicts=None, array_fields=None, timeout_on=None):
        self.calls = []
        self._db = FakeDB(collections, self.calls, conflicts or {}, array_fields or {}, timeout_on or set())
        self.closed = False

    def __getitem__(self, _name):
        return self._db

    def close(self):
        self.closed = True

    def __getattr__(self, item):
        if item in WRITE_METHODS:
            raise ForbiddenCall(f"write method on client: {item}")
        raise AttributeError(item)


def _all_collections_present():
    return {c: 5 for c in {x.collection for x in expected_indexes()}}


def test_classification_accounts_for_every_manifest_entry():
    entries = preflight.classify_manifest()
    assert len(entries) == len(expected_indexes())
    unique_count = sum(1 for e in entries if e["category"] == "unique_idempotency")
    perf_count = sum(1 for e in entries if e["category"] == "performance")
    assert unique_count + perf_count == len(entries)
    assert unique_count == sum(1 for x in expected_indexes() if x.unique)
    # No TTL support exists in the manifest schema today.
    assert all(e["ttl"] is False for e in entries)


def test_required_immediately_indexes_resolve_to_real_manifest_entries():
    names = {x.name for x in expected_indexes()}
    for _label, (collection, name) in preflight.REQUIRED_IMMEDIATELY.items():
        assert name in names
        idx = next(x for x in expected_indexes() if x.name == name)
        assert idx.collection == collection


def test_staged_order_partitions_all_entries_with_no_overlap():
    staged = preflight.staged_migration_order()
    all_names = staged["stage_1_critical_unique_security"] + staged["stage_2_ttl"] + staged["stage_3_performance"]
    assert sorted(all_names) == sorted(x.name for x in expected_indexes())
    assert staged["stage_2_ttl"] == []  # no TTL indexes declared


def test_ready_status_and_only_read_methods_called_when_no_conflicts():
    client = FakeClient(_all_collections_present())
    report = asyncio.run(preflight.run_preflight("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "READY"
    assert report["unique_conflicts"] == []
    assert client.closed
    assert all(call[0] in {"list_collection_names", "estimated_document_count", "command", "aggregate", "count_documents"} for call in client.calls)


def test_conflict_detection_reports_count_only_no_keys():
    collections = _all_collections_present()
    client = FakeClient(collections, conflicts={"tenants": 3})
    report = asyncio.run(preflight.run_preflight("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "BLOCKED"
    hit = next(c for c in report["unique_conflicts"] if c["collection"] == "tenants" and c["name"] == "uq_tenants_metaphora_org_id")
    assert hit["conflict_groups"] == 3
    # unique_conflicts entries are exactly {collection, name, conflict_groups} — no grouped key/_id leaks through.
    assert set(hit.keys()) == {"collection", "name", "conflict_groups"}


def test_missing_collection_is_not_created_and_reports_zero_counts():
    collections = _all_collections_present()
    del collections["tenants"]
    client = FakeClient(collections)
    report = asyncio.run(preflight.run_preflight("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["document_counts"]["tenants"] == 0
    # Missing collection: only list_collection_names() sees it; no read/write is ever attempted against it.
    assert all(call[1] != "tenants" for call in client.calls if call[0] in {"estimated_document_count", "command", "aggregate"})


def test_every_scanning_operation_receives_max_time_ms():
    client = FakeClient(_all_collections_present())
    asyncio.run(preflight.run_preflight("mongodb://fake", "db", client_factory=lambda uri, **kw: client, max_time_ms=1234))
    scanning_ops = {"estimated_document_count", "command", "aggregate", "count_documents"}
    scanning_calls = [c for c in client.calls if c[0] in scanning_ops]
    assert scanning_calls, "expected at least one scanning operation to run"
    assert all(c[-1] == 1234 for c in scanning_calls), scanning_calls


def test_max_time_ms_is_clamped_to_a_safe_maximum():
    assert preflight.resolve_max_time_ms({"PREFLIGHT_MAX_TIME_MS": "999999"}) == preflight.MAX_ALLOWED_MAX_TIME_MS
    assert preflight.resolve_max_time_ms({"PREFLIGHT_MAX_TIME_MS": "not-a-number"}) == preflight.DEFAULT_MAX_TIME_MS
    assert preflight.resolve_max_time_ms({}) == preflight.DEFAULT_MAX_TIME_MS
    assert preflight.resolve_max_time_ms({"PREFLIGHT_MAX_TIME_MS": "500"}) == 500


def test_timeout_fails_closed_with_incomplete_unsafe_and_nonzero_exit(capsys):
    client = FakeClient(_all_collections_present(), timeout_on={"aggregate"})
    code = preflight.main(
        environ={"MONGO_URL": "mongodb://fake", "DB_NAME": "db"},
        client_factory=lambda uri, **kw: client,
    )
    out = json.loads(capsys.readouterr().out)
    assert code != 0
    assert out["status"] == "INCOMPLETE_UNSAFE"
    assert out["status"] not in {"READY", "BLOCKED"}


def test_timeout_on_collstats_also_fails_closed():
    client = FakeClient(_all_collections_present(), timeout_on={"command"})
    report = asyncio.run(preflight.run_preflight("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "INCOMPLETE_UNSAFE"


def test_collation_guard_rejects_unmodeled_collation():
    modeled = SimpleNamespace(name="ok_index", collation=None)
    preflight.reject_unmodeled_collation(modeled)  # no raise
    unmodeled = SimpleNamespace(name="ci_index", collation={"locale": "en", "strength": 2})
    try:
        preflight.reject_unmodeled_collation(unmodeled)
        raise AssertionError("expected ValueError for unmodeled collation")
    except ValueError as exc:
        assert "ci_index" in str(exc)


def test_run_preflight_refuses_manifest_with_unmodeled_collation(monkeypatch):
    fake_index = SimpleNamespace(
        collection="tenants", name="ci_index", unique=True,
        fields=(("email", 1),), partial_filter=None, priority="P0",
        purpose="test", collation={"locale": "en"},
    )
    monkeypatch.setattr(preflight, "expected_indexes", lambda: (fake_index,))

    def forbidden(_uri, **_kw):
        raise AssertionError("must not connect when a manifest index has an unmodeled collation")

    try:
        asyncio.run(preflight.run_preflight("mongodb://fake", "db", client_factory=forbidden))
        raise AssertionError("expected ValueError before any connection attempt")
    except ValueError:
        pass


def test_array_valued_field_marks_index_unsupported_multikey_and_not_conflict_free():
    collections = _all_collections_present()
    client = FakeClient(collections, array_fields={"tenants": {"metaphora_org_id"}})
    report = asyncio.run(preflight.run_preflight("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "UNSUPPORTED_MULTKEY_PREFLIGHT"
    hit = next(m for m in report["multikey_unsupported"] if m["name"] == "uq_tenants_metaphora_org_id")
    assert hit["status"] == "UNSUPPORTED_MULTKEY_PREFLIGHT"
    # An index flagged multikey-unsupported must never also be claimed conflict-free.
    assert not any(c["name"] == "uq_tenants_metaphora_org_id" for c in report["unique_conflicts"])


def test_ordinary_and_compound_scalar_indexes_still_work_when_no_arrays_present():
    client = FakeClient(_all_collections_present())  # no array_fields configured anywhere
    report = asyncio.run(preflight.run_preflight("mongodb://fake", "db", client_factory=lambda uri, **kw: client))
    assert report["status"] == "READY"
    assert report["multikey_unsupported"] == []
    assert report["unique_conflicts"] == []
    # A representative compound-key unique index was actually checked.
    assert any(c[0] == "aggregate" and c[1] == "tenants" for c in client.calls)


def test_missing_env_fails_closed_without_connecting():
    def forbidden(_uri, **_kw):
        raise AssertionError("should never construct a client without MONGO_URL/DB_NAME")
    code = preflight.main(environ={}, client_factory=forbidden)
    assert code == 2


def test_classify_only_flag_needs_no_env_or_client(capsys):
    def forbidden(_uri, **_kw):
        raise AssertionError("classify-only must never construct a client")
    code = preflight.main(argv=["--classify-only"], environ={}, client_factory=forbidden)
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["classification"]) == len(expected_indexes())


def _called_names(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                yield func.attr
            elif isinstance(func, ast.Name):
                yield func.id


def test_module_source_contains_no_write_capable_calls():
    """AST-based: only real function/method calls count, not prose in docstrings/comments."""
    for mod in (preflight, apply_tool):
        tree = ast.parse(Path(mod.__file__).read_text())
        hits = sorted(set(_called_names(tree)) & WRITE_METHODS)
        assert hits == [], f"{mod.__name__}: write-capable call(s) found: {hits}"


def test_apply_plan_mode_never_touches_database(capsys):
    code = apply_tool.main(["--plan"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "PLAN"
    assert "staged_migration_order" in out


def test_apply_apply_mode_is_not_implemented_and_exits_nonzero(capsys):
    code = apply_tool.main(["--apply"])
    assert code == 3
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "NOT_IMPLEMENTED"


def test_apply_module_imports_no_mongo_driver():
    tree = ast.parse(Path(apply_tool.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("motor" in name for name in imported)
