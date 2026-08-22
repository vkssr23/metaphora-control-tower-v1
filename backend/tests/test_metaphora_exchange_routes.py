"""Real FastAPI route tests for POST /api/auth/metaphora/exchange (the
Metaphora Secure SSO handoff), using the same FakeDB/Collection fixtures
as test_rate_confirmation_routes.py/test_execution_eligibility_routes.py."""
import copy
import pytest
from fastapi import Header, HTTPException
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from test_rate_confirmation_routes import FakeDB, Collection, USERS, TA, h, server
from app.infrastructure import verify_sso_client


@pytest.fixture
def api(monkeypatch):
    db = FakeDB()
    for name in ("tenants",):
        setattr(db, name, Collection(name, db.events))
    monkeypatch.setattr(server, "db", db)
    server.app.dependency_overrides.clear()

    async def actor(x_test_user: str = Header("ops")):
        record = await db.users.find_one({"id": USERS.get(x_test_user, USERS["ops"])["id"]})
        if not record:
            raise HTTPException(401, "User unavailable")
        record.pop("_id", None)
        return record
    server.app.dependency_overrides[server.get_current_user] = actor
    yield TestClient(server.app), db
    server.app.dependency_overrides.clear()


def exchange(c, code="abc"):
    return c.post("/api/auth/metaphora/exchange", json={"code": code})


def _returns(value):
    """redeem_sso_code is `async def` in the real client — a plain lambda
    can't be awaited, so wrap the canned return value in a real coroutine
    function."""
    async def fake(settings, code):
        return value
    return fake


IDENTITY = {"status": "ok", "user_id": 7, "org_id": 42, "org_name": "Acme Freight",
            "email": "owner@example.com", "role": "admin", "email_verified": True}


def test_first_sso_login_bootstraps_tenant_and_owner(api, monkeypatch):
    c, db = api
    monkeypatch.setattr(verify_sso_client, "redeem_sso_code", _returns(IDENTITY))
    monkeypatch.setattr(verify_sso_client, "is_configured", lambda settings: True)

    r = exchange(c)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["role"] == "owner"
    assert body["user"]["email"] == "owner@example.com"
    assert "token" in body

    assert len(db.tenants.docs) == 1
    tenant = db.tenants.docs[0]
    assert tenant["metaphora_org_id"] == "42"
    assert db.assumptions.docs and db.assumptions.docs[0]["tenant_id"] == tenant["id"]
    assert any(e for e in db.audit_events.docs if e.get("action") == "tenant.metaphora_sso_user_created")


def test_second_org_member_lands_in_same_tenant(api, monkeypatch):
    c, db = api
    monkeypatch.setattr(verify_sso_client, "is_configured", lambda settings: True)
    monkeypatch.setattr(verify_sso_client, "redeem_sso_code", _returns(IDENTITY))
    first = exchange(c).json()
    first_tenant_id = first["user"]["tenant_id"]
    assert len(db.tenants.docs) == 1

    second_identity = {**IDENTITY, "user_id": 8, "email": "teammate@example.com", "role": "member"}
    monkeypatch.setattr(verify_sso_client, "redeem_sso_code", _returns(second_identity))
    second = exchange(c).json()

    assert len(db.tenants.docs) == 1  # no second tenant created
    assert second["user"]["tenant_id"] == first_tenant_id
    assert second["user"]["role"] == "viewer"  # safe default for a non-first user


def test_returning_user_role_not_overwritten(api, monkeypatch):
    c, db = api
    monkeypatch.setattr(verify_sso_client, "is_configured", lambda settings: True)
    monkeypatch.setattr(verify_sso_client, "redeem_sso_code", _returns(IDENTITY))
    first = exchange(c).json()

    # Control Tower admin promotes this user to "dispatcher" locally.
    db.users.docs[-1]["role"] = "dispatcher"

    second = exchange(c).json()
    assert second["user"]["role"] == "dispatcher"
    assert second["user"]["tenant_id"] == first["user"]["tenant_id"]


def test_invalid_or_expired_code_returns_400(api, monkeypatch):
    c, db = api
    monkeypatch.setattr(verify_sso_client, "is_configured", lambda settings: True)
    monkeypatch.setattr(verify_sso_client, "redeem_sso_code", _returns({"status": "invalid_or_expired"}))
    r = exchange(c)
    assert r.status_code == 400
    assert not db.tenants.docs


def test_not_configured_returns_503(api, monkeypatch):
    c, db = api
    monkeypatch.setattr(verify_sso_client, "is_configured", lambda settings: False)
    r = exchange(c)
    assert r.status_code == 503
    assert not db.tenants.docs


def test_email_collision_with_unrelated_tenant_returns_409(api, monkeypatch):
    c, db = api
    db.users.docs.append({"id": "U-existing", "email": "owner@example.com", "name": "Existing",
                           "role": "viewer", "tenant_id": "ten_" + "z" * 32, "password": "x", "created_at": "now"})
    monkeypatch.setattr(verify_sso_client, "is_configured", lambda settings: True)
    monkeypatch.setattr(verify_sso_client, "redeem_sso_code", _returns(IDENTITY))

    r = exchange(c)
    assert r.status_code == 409
    assert not db.tenants.docs


def test_concurrent_first_logins_do_not_duplicate_tenant(api, monkeypatch):
    c, db = api
    monkeypatch.setattr(verify_sso_client, "is_configured", lambda settings: True)
    monkeypatch.setattr(verify_sso_client, "redeem_sso_code", _returns(IDENTITY))

    # Simulate another request already having won the race: a tenant for
    # this Verify org already exists, but this caller's own find_one still
    # missed it (classic TOCTOU), so its insert_one hits the unique index.
    winning_tenant = {"id": "ten_" + "w" * 32, "name": "Acme Freight", "status": "active",
                      "created_at": "now", "updated_at": "now", "metaphora_org_id": "42"}
    db.tenants.docs.append(winning_tenant)

    async def raising_insert(doc):
        raise DuplicateKeyError("E11000 duplicate key")
    monkeypatch.setattr(db.tenants, "insert_one", raising_insert)

    r = exchange(c)
    assert r.status_code == 200, r.text
    assert len(db.tenants.docs) == 1  # no duplicate created
    assert r.json()["user"]["tenant_id"] == winning_tenant["id"]


def test_existing_signup_login_unaffected(api):
    c, db = api
    r = c.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
    assert r.status_code == 401
