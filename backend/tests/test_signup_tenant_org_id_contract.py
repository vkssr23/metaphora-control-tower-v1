"""Proves /api/auth/signup writes an unlinked tenant with metaphora_org_id
genuinely MISSING (not present-as-null), and that /api/auth/metaphora/exchange
rejects a blank (whitespace-only) org_id from Verify rather than writing it."""
import pytest
from fastapi.testclient import TestClient

from test_rate_confirmation_routes import FakeDB, Collection, server
from app.infrastructure import verify_sso_client


@pytest.fixture
def api(monkeypatch):
    db = FakeDB()
    for name in ("tenants",):
        setattr(db, name, Collection(name, db.events))
    monkeypatch.setattr(server, "db", db)
    server.app.dependency_overrides.clear()
    yield TestClient(server.app), db
    server.app.dependency_overrides.clear()


def test_signup_tenant_has_no_metaphora_org_id_key_at_all(api):
    c, db = api
    r = c.post("/api/auth/signup", json={"email": "new@example.com", "password": "at-least-12-chars", "name": "New"})
    assert r.status_code == 200, r.text
    assert len(db.tenants.docs) == 1
    assert "metaphora_org_id" not in db.tenants.docs[0]


def _returns(value):
    async def fake(settings, code):
        return value
    return fake


def test_blank_org_id_from_verify_is_rejected_not_written(api, monkeypatch):
    c, db = api
    identity = {"status": "ok", "user_id": 1, "org_id": "   ", "org_name": "Acme",
                "email": "owner@example.com", "role": "admin", "email_verified": True}
    monkeypatch.setattr(verify_sso_client, "is_configured", lambda settings: True)
    monkeypatch.setattr(verify_sso_client, "redeem_sso_code", _returns(identity))

    r = c.post("/api/auth/metaphora/exchange", json={"code": "abc"})
    assert r.status_code == 502
    assert not db.tenants.docs
