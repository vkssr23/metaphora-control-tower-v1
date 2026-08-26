"""Proves the one-purpose synthetic-tenant cleanup script: dry-run by
default, precheck aborts on any single mismatch, transactional delete with
real rollback-equivalent semantics on failure (no partial cleanup),
confirmation-gated execute, idempotent re-run, and no secret/email output."""
import asyncio
import json
from types import SimpleNamespace

from pymongo.errors import ExecutionTimeout

from app.production_integrity import TENANT_SCOPED
from scripts import cleanup_synthetic_gate_verify_tenant as cleanup

TENANT_ID = cleanup.TENANT_ID
USER_ID = cleanup.USER_ID
GOOD_CREATED_AT = "2026-08-26T00:45:30+00:00"
GOOD_EMAIL = f"gate-verify-123@{cleanup.EMAIL_DOMAIN_MARKER}"


class FakeCollection:
    def __init__(self, name, db):
        self.name = name
        self._db = db
        self.docs = []

    async def find_one(self, filt, projection=None, max_time_ms=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in filt.items()):
                return dict(d)
        return None

    def find(self, filt, projection=None, max_time_ms=None):
        matches = [dict(d) for d in self.docs if all(d.get(k) == v for k, v in filt.items())]
        return SimpleNamespace(to_list=lambda length=None: _to_list(matches))

    async def count_documents(self, filt, maxTimeMS=None):
        return sum(1 for d in self.docs if all(d.get(k) == v for k, v in filt.items()))

    async def delete_one(self, filt, session=None):
        match = next((d for d in self.docs if all(d.get(k) == v for k, v in filt.items())), None)
        if match is None:
            return SimpleNamespace(deleted_count=0)
        if getattr(self._db, "fail_delete_on", None) == self.name:
            raise ExecutionTimeout("simulated failure mid-transaction")
        if session is not None:
            session.pending.append((self.name, match["id"]))
            return SimpleNamespace(deleted_count=1)
        self.docs = [d for d in self.docs if d is not match]
        return SimpleNamespace(deleted_count=1)


async def _to_list(items):
    return items


class FakeSession:
    def __init__(self, db):
        self.db = db
        self.pending = []

    def start_transaction(self):
        return self

    async def __aenter__(self):
        self.pending = []
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            for cname, doc_id in self.pending:
                coll = getattr(self.db, cname)
                coll.docs = [d for d in coll.docs if d.get("id") != doc_id]
        return False  # never swallow exceptions

    async def end_session(self):
        pass


class FakeAdmin:
    def __init__(self, hello):
        self._hello = hello

    async def command(self, name):
        assert name == "hello"
        return self._hello


class FakeDB:
    def __init__(self, transactions_supported=True, fail_delete_on=None):
        for name in sorted(TENANT_SCOPED | {"audit_events", "tenants"}):
            setattr(self, name, FakeCollection(name, self))
        self.fail_delete_on = fail_delete_on
        self._transactions_supported = transactions_supported

    def __getitem__(self, name):
        return getattr(self, name)


class FakeClient:
    def __init__(self, db):
        self._db = db
        self.admin = FakeAdmin(
            {"setName": "rs0", "logicalSessionTimeoutMinutes": 30} if db._transactions_supported else {}
        )
        self.closed = False

    def __getitem__(self, _name):
        return self._db

    async def start_session(self):
        return FakeSession(self._db)

    def close(self):
        self.closed = True


def _seed_valid_state(db, *, tenant_created=GOOD_CREATED_AT, user_created=GOOD_CREATED_AT, email=GOOD_EMAIL, extra_business_record=False):
    db.tenants.docs.append({"id": TENANT_ID, "created_at": tenant_created})
    db.users.docs.append({"id": USER_ID, "tenant_id": TENANT_ID, "created_at": user_created, "email": email})
    if extra_business_record:
        db.loads.docs.append({"id": "L1", "tenant_id": TENANT_ID})


def _factory(db):
    return lambda uri, **kw: FakeClient(db)


def test_dry_run_is_default_and_makes_no_changes():
    db = FakeDB()
    _seed_valid_state(db)
    code = cleanup.main(environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 0
    assert len(db.tenants.docs) == 1 and len(db.users.docs) == 1  # untouched


def test_dry_run_reports_ok_true_for_valid_state(capsys):
    db = FakeDB()
    _seed_valid_state(db)
    cleanup.main(environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "DRY_RUN" and out["ok"] is True
    assert all(out["checks"].values())


def test_execute_without_confirmation_phrase_is_refused():
    db = FakeDB()
    _seed_valid_state(db)
    code = cleanup.main(argv=["--execute", "--confirm", "wrong phrase"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 2
    assert len(db.tenants.docs) == 1  # nothing deleted


def test_execute_without_confirm_flag_at_all_is_refused():
    db = FakeDB()
    _seed_valid_state(db)
    code = cleanup.main(argv=["--execute"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 2
    assert len(db.tenants.docs) == 1


def test_mismatch_wrong_user_count_aborts():
    db = FakeDB()
    _seed_valid_state(db)
    db.users.docs.append({"id": "OTHER", "tenant_id": TENANT_ID, "created_at": GOOD_CREATED_AT, "email": GOOD_EMAIL})
    code = cleanup.main(argv=["--execute", "--confirm", cleanup.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 2
    assert len(db.tenants.docs) == 1 and len(db.users.docs) == 2


def test_mismatch_business_records_present_aborts():
    db = FakeDB()
    _seed_valid_state(db, extra_business_record=True)
    code = cleanup.main(argv=["--execute", "--confirm", cleanup.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 2
    assert len(db.tenants.docs) == 1  # not deleted


def test_mismatch_outside_creation_window_aborts():
    db = FakeDB()
    _seed_valid_state(db, tenant_created="2026-08-25T00:00:00+00:00")
    code = cleanup.main(argv=["--execute", "--confirm", cleanup.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 2
    assert len(db.tenants.docs) == 1


def test_mismatch_missing_synthetic_email_marker_aborts():
    db = FakeDB()
    _seed_valid_state(db, email="real-customer@acmefreight.com")
    code = cleanup.main(argv=["--execute", "--confirm", cleanup.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 2
    assert len(db.tenants.docs) == 1


def test_no_transaction_support_fails_closed_no_partial_delete():
    db = FakeDB(transactions_supported=False)
    _seed_valid_state(db)
    code = cleanup.main(argv=["--execute", "--confirm", cleanup.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 2
    assert len(db.tenants.docs) == 1 and len(db.users.docs) == 1


def test_transaction_failure_mid_delete_rolls_back_no_partial_cleanup():
    db = FakeDB(fail_delete_on="tenants")  # user delete succeeds first, tenant delete raises
    _seed_valid_state(db)
    code = cleanup.main(argv=["--execute", "--confirm", cleanup.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 2
    # Neither commit happened — the user "delete" was only staged in the
    # session, never applied, because the transaction never committed.
    assert len(db.tenants.docs) == 1 and len(db.users.docs) == 1


def test_successful_execute_deletes_both_and_preserves_audit_events():
    db = FakeDB()
    _seed_valid_state(db)
    db.audit_events.docs.append({"id": "AE1", "tenant_id": TENANT_ID})
    code = cleanup.main(argv=["--execute", "--confirm", cleanup.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 0
    assert db.tenants.docs == [] and db.users.docs == []
    assert len(db.audit_events.docs) == 1  # preserved, not deleted


def test_rerun_after_success_is_idempotent_already_cleaned_up():
    db = FakeDB()  # nothing seeded — simulates the post-cleanup state
    code = cleanup.main(argv=["--execute", "--confirm", cleanup.CONFIRMATION], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=_factory(db))
    assert code == 0


def test_output_never_contains_email_or_secrets(capsys):
    db = FakeDB()
    _seed_valid_state(db)
    db.audit_events.docs.append({"id": "AE1", "tenant_id": TENANT_ID})
    cleanup.main(argv=["--execute", "--confirm", cleanup.CONFIRMATION], environ={"MONGO_URL": "mongodb://user:pw@host/db", "DB_NAME": "proddb"}, client_factory=_factory(db))
    out = capsys.readouterr().out
    assert GOOD_EMAIL not in out
    assert "pw@host" not in out and "proddb" not in out


def test_missing_env_fails_closed_without_connecting():
    def forbidden(_uri, **_kw):
        raise AssertionError("must not connect without MONGO_URL/DB_NAME")
    code = cleanup.main(environ={}, client_factory=forbidden)
    assert code == 2


def test_confirmation_checked_before_any_connection():
    def forbidden(_uri, **_kw):
        raise AssertionError("must not connect when confirmation phrase is wrong")
    code = cleanup.main(argv=["--execute", "--confirm", "nope"], environ={"MONGO_URL": "x", "DB_NAME": "y"}, client_factory=forbidden)
    assert code == 2
