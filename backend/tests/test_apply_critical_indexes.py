"""Proves the critical-index apply tool: plan-only by default, confirmation
gated, aborts before any write on conflict/drift/multikey/timeout, creates
only what's missing, verifies each creation by read-back, supports safe
idempotent continuation, and never drops/replaces an existing index."""
import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from pymongo.errors import ExecutionTimeout

from app.infrastructure.index_manifest import expected_indexes
from scripts import apply_critical_indexes as apply_tool

CRITICAL = apply_tool.CRITICAL_INDEX_NAMES
WRITE_METHODS = {
    "insert_one", "insert_many", "update_one", "update_many", "delete_one",
    "delete_many", "drop_index", "drop_indexes", "drop", "replace_one",
    "find_one_and_update", "find_one_and_delete", "find_one_and_replace",
    "bulk_write", "rename", "drop_database",
}


class FakeCursor:
    def __init__(self, items):
        self._items = items

    async def to_list(self, length=None):
        return list(self._items)


class FakeCollection:
    def __init__(self, name, db):
        self.name, self._db = name, db
        self.indexes = []  # list of {"name","key","unique","partialFilterExpression"}

    def list_indexes(self):  # real motor: sync call returning a cursor, like aggregate()/find()
        return FakeCursor(list(self.indexes))

    def aggregate(self, pipeline, maxTimeMS=None):
        if self.name in self._db.force_conflict_on:
            return FakeCursor([{"conflicts": 1}])
        return FakeCursor([])

    async def count_documents(self, filt, limit=None, maxTimeMS=None):
        field = next(iter(filt))
        return 1 if (self.name, field) in self._db.force_multikey_on else 0

    async def create_index(self, keys, name, unique, partialFilterExpression=None):
        self._db.create_index_calls.append((self.name, name))
        if self.name in self._db.fail_create_on:
            raise ExecutionTimeout("simulated create_index failure")
        self.indexes.append({
            "name": name, "key": dict(keys), "unique": unique,
            "partialFilterExpression": partialFilterExpression,
        })

    def __getattr__(self, item):
        if item in WRITE_METHODS:
            raise AssertionError(f"write method on collection: {item}")
        raise AttributeError(item)


class FakeDB:
    def __init__(self, force_conflict_on=None, force_multikey_on=None, fail_create_on=None, seed_matching=False, seed_drift_on=None):
        self.force_conflict_on = force_conflict_on or set()
        self.force_multikey_on = force_multikey_on or set()
        self.fail_create_on = fail_create_on or set()
        self.create_index_calls = []
        self.users = FakeCollection("users", self)
        self.tenants = FakeCollection("tenants", self)
        if seed_matching:
            for index in (x for x in expected_indexes() if x.name in CRITICAL):
                self[index.collection].indexes.append({
                    "name": index.name, "key": dict(index.fields), "unique": index.unique,
                    "partialFilterExpression": index.partial_filter,
                })
        if seed_drift_on:
            for index in (x for x in expected_indexes() if x.name == seed_drift_on):
                self[index.collection].indexes.append({
                    "name": index.name, "key": dict(index.fields), "unique": False,  # wrong on purpose
                    "partialFilterExpression": index.partial_filter,
                })

    async def list_collection_names(self):
        return ["users", "tenants"]

    def __getitem__(self, name):
        return getattr(self, name)


class FakeClient:
    def __init__(self, db):
        self._db = db
        self.closed = False

    def __getitem__(self, _name):
        return self._db

    def close(self):
        self.closed = True


def _factory(db):
    return lambda uri, **kw: FakeClient(db)


def test_default_mode_is_plan_and_never_connects():
    def forbidden(_uri, **_kw):
        raise AssertionError("plan mode must never construct a client")
    code = apply_tool.main(environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=forbidden)
    assert code == 0


def test_plan_output_matches_manifest_exactly(capsys):
    apply_tool.main(argv=["--plan"], client_factory=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")))
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "PLAN"
    by_name = {x.name: x for x in expected_indexes()}
    assert [i["name"] for i in out["indexes"]] == list(CRITICAL)
    for entry in out["indexes"]:
        idx = by_name[entry["name"]]
        assert entry["collection"] == idx.collection
        assert entry["fields"] == [list(f) for f in idx.fields]
        assert entry["unique"] == idx.unique
        assert entry["partial_filter"] == idx.partial_filter


def test_apply_without_confirmation_is_refused_before_connecting():
    def forbidden(_uri, **_kw):
        raise AssertionError("must not connect without the exact confirmation phrase")
    code = apply_tool.main(argv=["--apply"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=forbidden)
    assert code == 2
    code2 = apply_tool.main(argv=["--apply", "--confirm", "wrong"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=forbidden)
    assert code2 == 2


def test_conflict_aborts_before_any_write():
    db = FakeDB(force_conflict_on={"users"})
    code = apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 2
    assert db.users.indexes == [] and db.tenants.indexes == []


def test_multikey_aborts_before_any_write():
    db = FakeDB(force_multikey_on={("users", "email")})
    code = apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 2
    assert db.users.indexes == [] and db.tenants.indexes == []


def test_drift_aborts_globally_before_any_write():
    db = FakeDB(seed_drift_on="uq_tenants_metaphora_org_id")  # wrong unique flag
    code = apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 2
    # Nothing else got created either, even though users had no drift.
    assert db.users.indexes == []
    assert db.tenants.indexes == [{"name": "uq_tenants_metaphora_org_id", "key": {"metaphora_org_id": 1}, "unique": False, "partialFilterExpression": {"metaphora_org_id": {"$type": "string", "$gt": ""}}}]


def test_successful_apply_creates_all_three_and_verifies_readback(capsys):
    db = FakeDB()
    code = apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["status"] == "COMPLETE"
    assert set(out["created"]) == set(CRITICAL)
    assert db.users.indexes and db.tenants.indexes
    created_names = {i["name"] for i in db.users.indexes} | {i["name"] for i in db.tenants.indexes}
    assert created_names == set(CRITICAL)


def test_idempotent_rerun_when_all_already_present(capsys):
    db = FakeDB(seed_matching=True)
    code = apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["status"] == "COMPLETE"
    assert out["created"] == []
    assert set(out["skipped_already_present"]) == set(CRITICAL)


def test_partial_completion_stops_and_reports_without_rollback(capsys):
    db = FakeDB(fail_create_on={"tenants"})  # users' index(es) succeed, tenants' fails
    code = apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["status"] == "PARTIAL_FAILURE"
    assert out["failed_index"] == "uq_tenants_metaphora_org_id"
    # uq_users_email was created first and must NOT be rolled back.
    assert any(i["name"] == "uq_users_email" for i in db.users.indexes)
    assert "uq_users_email" in out["created_so_far"]


def test_rerun_after_partial_completion_only_creates_the_missing_one(capsys):
    db = FakeDB()
    apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    capsys.readouterr()  # discard first run's output
    # Simulate a fresh process re-running against the now-partially-migrated db.
    db.users.indexes = [i for i in db.users.indexes if i["name"] != "uq_users_tenant_id_id"]
    code = apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["status"] == "COMPLETE"
    assert out["created"] == ["uq_users_tenant_id_id"]
    assert set(out["skipped_already_present"]) == {"uq_users_email", "uq_tenants_metaphora_org_id"}


class TimeoutDB(FakeDB):
    async def list_collection_names(self):
        raise ExecutionTimeout("simulated")


def test_timeout_during_validation_fails_closed():
    db = TimeoutDB()
    code = apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 2
    assert db.users.indexes == [] and db.tenants.indexes == []


def test_output_never_contains_env_values(capsys):
    db = FakeDB()
    apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "mongodb://user:pw@host/db", "DB_NAME": "proddb"}, client_factory=_factory(db))
    out = capsys.readouterr().out
    assert "pw@host" not in out and "proddb" not in out


# ---- --check mode ----------------------------------------------------------

def test_check_performs_zero_writes_on_clean_db(capsys):
    db = FakeDB()
    code = apply_tool.main(argv=["--check"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["status"] == "READY"
    assert db.create_index_calls == []
    assert db.users.indexes == [] and db.tenants.indexes == []


def test_check_performs_zero_writes_even_when_blocked(capsys):
    db = FakeDB(force_conflict_on={"users"})
    code = apply_tool.main(argv=["--check"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["status"] == "BLOCKED"
    assert db.create_index_calls == []


def test_check_reports_exact_three_index_production_plan(capsys):
    db = FakeDB()
    code = apply_tool.main(argv=["--check"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["status"] == "READY"
    covered = set(out["correct"]) | set(out["missing"]) | set(out["drifted"])
    assert covered == set(CRITICAL)
    assert set(out["missing"]) == set(CRITICAL)  # nothing pre-seeded
    assert out["correct"] == [] and out["drifted"] == []


def test_check_and_apply_share_the_same_validator(monkeypatch):
    """Patches _validate itself and proves both --check and --apply call it
    with identical arguments — the two modes cannot diverge because they
    run through one shared function, not parallel implementations."""
    calls = []
    real_validate = apply_tool._validate

    async def spy(db, max_time_ms):
        calls.append((db, max_time_ms))
        return await real_validate(db, max_time_ms)

    monkeypatch.setattr(apply_tool, "_validate", spy)

    db = FakeDB()
    apply_tool.main(argv=["--check"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert len(calls) == 2
    assert calls[0][1] == calls[1][1]  # same max_time_ms resolution
    assert calls[0][0] is db and calls[1][0] is db  # same db, same validator function


def test_check_and_apply_agree_on_conflict(capsys):
    db_check = FakeDB(force_conflict_on={"users"})
    code_check = apply_tool.main(argv=["--check"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db_check))
    check_out = json.loads(capsys.readouterr().out)

    db_apply = FakeDB(force_conflict_on={"users"})
    code_apply = apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db_apply))
    apply_out = json.loads(capsys.readouterr().out)

    assert code_check == 1 and check_out["status"] == "BLOCKED"
    assert code_apply == 2 and apply_out["status"] == "ABORT_VALIDATION_FAILED"
    assert apply_out["per_index"]["uq_users_email"]["conflict_groups"] == check_out["conflict_counts"]["uq_users_email"]
    assert db_check.create_index_calls == [] and db_apply.create_index_calls == []


def test_check_and_apply_agree_on_drift(capsys):
    db_check = FakeDB(seed_drift_on="uq_tenants_metaphora_org_id")
    apply_tool.main(argv=["--check"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db_check))
    check_out = json.loads(capsys.readouterr().out)

    db_apply = FakeDB(seed_drift_on="uq_tenants_metaphora_org_id")
    apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db_apply))
    apply_out = json.loads(capsys.readouterr().out)

    assert check_out["status"] == "BLOCKED" and "uq_tenants_metaphora_org_id" in check_out["drifted"]
    assert apply_out["status"] == "ABORT_VALIDATION_FAILED"
    assert apply_out["per_index"]["uq_tenants_metaphora_org_id"]["state"] == "DRIFT"
    assert db_check.create_index_calls == [] and db_apply.create_index_calls == []


def test_check_and_apply_agree_on_timeout(capsys):
    db_check = TimeoutDB()
    apply_tool.main(argv=["--check"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db_check))
    check_out = json.loads(capsys.readouterr().out)

    db_apply = TimeoutDB()
    apply_tool.main(argv=["--apply", "--confirm", apply_tool.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db_apply))
    apply_out = json.loads(capsys.readouterr().out)

    assert check_out["status"] == "INCOMPLETE"
    assert apply_out["status"] == "INCOMPLETE_UNSAFE"
    assert db_check.create_index_calls == [] and db_apply.create_index_calls == []


def test_plan_mode_stays_offline_when_check_not_requested():
    def forbidden(_uri, **_kw):
        raise AssertionError("--plan must never connect")
    code = apply_tool.main(argv=["--plan"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=forbidden)
    assert code == 0


def _called_names(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                yield func.attr
            elif isinstance(func, ast.Name):
                yield func.id


def test_module_never_calls_drop_or_replace():
    tree = ast.parse(Path(apply_tool.__file__).read_text())
    hits = sorted(set(_called_names(tree)) & WRITE_METHODS)
    assert hits == [], f"write-capable call(s) found: {hits}"


def test_scopes_exactly_three_named_indexes():
    assert len(apply_tool._critical_indexes()) == 3
    assert {x.name for x in apply_tool._critical_indexes()} == set(CRITICAL)
