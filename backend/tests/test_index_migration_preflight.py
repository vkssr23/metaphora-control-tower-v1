"""Proves the index migration preflight is structurally read-only and correct."""
import ast
import asyncio
import json
from pathlib import Path

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
    def __init__(self, name, calls, count=0, conflicts=None):
        self._name, self._calls, self._count = name, calls, count
        self._conflicts = conflicts or 0

    async def estimated_document_count(self):
        self._calls.append(("estimated_document_count", self._name))
        return self._count

    def aggregate(self, pipeline):
        self._calls.append(("aggregate", self._name))
        return FakeCursor([{"conflicts": self._conflicts}] if self._conflicts else [])

    def __getattr__(self, item):
        if item in WRITE_METHODS:
            raise ForbiddenCall(f"write method on collection: {item}")
        raise AttributeError(item)


class FakeDB:
    def __init__(self, collections, calls, conflicts):
        self._collections, self._calls, self._conflicts = collections, calls, conflicts

    async def list_collection_names(self):
        self._calls.append(("list_collection_names",))
        return list(self._collections.keys())

    async def command(self, name, target=None):
        self._calls.append(("command", name, target))
        assert name == "collStats"
        return {"storageSize": 1024, "avgObjSize": 100}

    def __getitem__(self, name):
        return FakeCollection(name, self._calls, self._collections.get(name, 0), self._conflicts.get(name))

    def __getattr__(self, item):
        if item in WRITE_METHODS:
            raise ForbiddenCall(f"write method on db: {item}")
        raise AttributeError(item)


class FakeClient:
    def __init__(self, collections, conflicts=None):
        self.calls = []
        self._db = FakeDB(collections, self.calls, conflicts or {})
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
    assert all(call[0] in {"list_collection_names", "estimated_document_count", "command", "aggregate"} for call in client.calls)


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
