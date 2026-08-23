"""Isolated tests for Emergency Security Patch 0A.1.

These tests never connect to MongoDB, call a provider, make network requests,
or execute the destructive seed body.
"""
import asyncio
from dataclasses import replace
import os
import re
import sys
from types import ModuleType

# Overwrite every safety-critical value before importing the application so a
# developer or production environment can never leak into this suite.
os.environ["JWT_SECRET"] = "isolated-test-only-secret-value-over-32-characters"
os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1/no-network-test"
os.environ["DB_NAME"] = "metaphora_security_isolated_fake_db"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["APP_ENV"] = "test"
os.environ["ALLOW_SEED_ENDPOINT"] = "false"

import bcrypt
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest

import server
from app.config import force_seed_allowed, parse_cors_origins, validate_jwt_secret
from app.permissions import ROLE_CAPABILITIES
from app.security import authenticated_user_dependency, create_token

VALID_TENANT = "ten_" + "a" * 32


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *args, **kwargs):
        return self

    async def to_list(self, length):
        return self.docs[:length]


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.inject_on_insert = {}

    async def find_one(self, query, *args):
        for doc in self.docs:
            matches = True
            for key, expected in query.items():
                actual = doc.get(key)
                if isinstance(expected, re.Pattern):
                    matches = isinstance(actual, str) and expected.fullmatch(actual) is not None
                else:
                    matches = actual == expected
                if not matches:
                    break
            if matches:
                return dict(doc)
        return None

    def find(self, *args, **kwargs):
        return FakeCursor([dict(doc) for doc in self.docs])

    async def insert_one(self, doc):
        doc.update(self.inject_on_insert)
        self.docs.append(dict(doc))
        return object()

    async def update_one(self, *args, **kwargs):
        return object()

    async def delete_one(self, *args, **kwargs):
        return object()


class FakeDB:
    def __init__(self, users=None, loads=None):
        self.users = FakeCollection(users)
        self.loads = FakeCollection(loads)
        self.activity = FakeCollection()
        self.audit_events = FakeCollection()
        self.trucks = FakeCollection()
        self.drivers = FakeCollection()
        self.documents = FakeCollection()
        self.invoices = FakeCollection()
        self.assumptions = FakeCollection()
        self.tenants = FakeCollection()


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    fake = FakeDB(loads=[{"id": "L1", "customer": "Test", "tenant_id": VALID_TENANT}])
    monkeypatch.setattr(server, "db", fake)
    server.app.dependency_overrides.clear()
    yield fake
    server.app.dependency_overrides.clear()


def as_role(role):
    async def dependency():
        return {"id": f"U-{role}", "email": f"{role}@test.invalid", "name": role.title(), "role": role, "tenant_id": VALID_TENANT}
    server.app.dependency_overrides[server.get_current_user] = dependency


def test_route_table_has_only_four_public_application_routes():
    expected_public = {
        ("GET", "/api/"),
        ("POST", "/api/auth/signup"),
        ("POST", "/api/auth/login"),
        # Metaphora Secure SSO handoff: establishes a brand-new session from
        # a code redeemed server-to-server against Verify, so it can carry
        # no prior Control Tower credential of its own — same reason
        # signup/login are unauthenticated.
        ("POST", "/api/auth/metaphora/exchange"),
    }
    actual_public = set()

    def expanded_application_routes(routes):
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            elif hasattr(route, "original_router"):
                yield from expanded_application_routes(route.original_router.routes)

    def dependency_calls(dependant):
        calls = {dependency.call for dependency in dependant.dependencies}
        for dependency in dependant.dependencies:
            calls.update(dependency_calls(dependency))
        return calls

    application_routes = list(expanded_application_routes(server.app.routes))
    assert application_routes
    for route in application_routes:
        calls = dependency_calls(route.dependant)
        for method in route.methods - {"HEAD", "OPTIONS"}:
            policy = (method, route.path)
            if server.get_current_user not in calls:
                actual_public.add(policy)
            else:
                assert policy not in expected_public
    assert actual_public == expected_public
    assert server.app.docs_url is None and server.app.redoc_url is None and server.app.openapi_url is None


def test_missing_token_returns_401_on_read_and_write():
    client = TestClient(server.app)
    assert client.get("/api/loads").status_code == 401
    assert client.post("/api/loads", json={}).status_code == 401


def test_viewer_can_read_but_cannot_mutate():
    as_role("viewer")
    client = TestClient(server.app)
    assert client.get("/api/loads").status_code == 200
    assert client.post("/api/loads", json={}).status_code == 403


EXPECTED_CAPABILITIES = {
    "owner": {"operational", "safety", "finance", "ai"},
    "admin": {"operational", "safety", "finance", "ai"},
    "dispatcher": {"operational"},
    "operations": {"operational"},
    "safety": {"safety"},
    "compliance": {"safety"},
    "finance": {"finance"},
    "viewer": set(),
}


@pytest.mark.parametrize("role,expected", EXPECTED_CAPABILITIES.items())
def test_complete_role_capability_matrix(role, expected):
    assert ROLE_CAPABILITIES[role] == expected
    user = {"id": "U1", "role": role}
    dependencies = {
        "operational": server.operational_write,
        "safety": server.safety_write,
        "finance": server.finance_write,
        "ai": server.ai_access,
    }
    for capability, dependency in dependencies.items():
        if capability in expected:
            assert asyncio.run(dependency(user=user)) == user
        else:
            with pytest.raises(HTTPException) as exc:
                asyncio.run(dependency(user=user))
            assert exc.value.status_code == 403
    if role == "owner":
        assert asyncio.run(server.owner_only(user=user)) == user
    else:
        with pytest.raises(HTTPException):
            asyncio.run(server.owner_only(user=user))


@pytest.mark.parametrize("role", ["dispatcher", "operations"])
def test_operations_roles_cannot_write_safety_or_finance(role):
    as_role(role)
    client = TestClient(server.app)
    assert client.post("/api/loads", json={
        "customer": "Customer", "pickup_address": "A", "delivery_address": "B"
    }).status_code == 200
    assert client.post("/api/trucks", json={"truck_number": "T1"}).status_code == 403
    assert client.post("/api/invoices", json={"load_id": "L1"}).status_code == 403


@pytest.mark.parametrize("role", ["safety", "compliance"])
def test_safety_roles_cannot_write_operational_or_finance(role):
    as_role(role)
    client = TestClient(server.app)
    assert client.post("/api/trucks", json={"truck_number": "T1"}).status_code == 200
    assert client.post("/api/loads", json={}).status_code == 403
    assert client.post("/api/invoices", json={"load_id": "L1"}).status_code == 403


def test_finance_cannot_write_operational_or_safety():
    as_role("finance")
    client = TestClient(server.app)
    assert client.post("/api/invoices", json={"load_id": "L1"}).status_code == 409
    assert client.post("/api/loads", json={}).status_code == 403
    assert client.post("/api/trucks", json={"truck_number": "T1"}).status_code == 403


def install_fake_ai_provider(monkeypatch):
    root = ModuleType("emergentintegrations")
    llm = ModuleType("emergentintegrations.llm")
    chat = ModuleType("emergentintegrations.llm.chat")

    class UserMessage:
        def __init__(self, text): self.text = text

    class TextDelta:
        content = "mocked"

    class StreamDone:
        pass

    class LlmChat:
        def __init__(self, **kwargs): pass
        def with_model(self, *args): return self
        async def stream_message(self, message):
            yield StreamDone()

    chat.LlmChat, chat.UserMessage = LlmChat, UserMessage
    chat.TextDelta, chat.StreamDone = TextDelta, StreamDone
    monkeypatch.setitem(sys.modules, "emergentintegrations", root)
    monkeypatch.setitem(sys.modules, "emergentintegrations.llm", llm)
    monkeypatch.setitem(sys.modules, "emergentintegrations.llm.chat", chat)


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_and_admin_can_access_ai_with_mocked_provider(role, monkeypatch):
    install_fake_ai_provider(monkeypatch)
    monkeypatch.setenv("EMERGENT_LLM_KEY", "test-provider-key")
    as_role(role)
    assert TestClient(server.app).post("/api/ai/chat", json={"message": "hello"}).status_code == 200


def test_viewer_cannot_access_ai_and_admin_cannot_access_seed(monkeypatch):
    as_role("viewer")
    assert TestClient(server.app).post("/api/ai/chat", json={"message": "hello"}).status_code == 403
    as_role("admin")
    monkeypatch.setattr(server, "settings", replace(server.settings, allow_seed_endpoint=True, app_env="test"))
    assert TestClient(server.app).post("/api/seed?force=true").status_code == 403


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_public_signup_rejects_privileged_roles(role):
    response = TestClient(server.app).post("/api/auth/signup", json={
        "email": f"{role}@example.com", "password": "long-enough-password", "name": "Test", "role": role,
    })
    assert response.status_code == 403


def test_signup_allowlists_response_and_normalizes_email(isolated_db):
    isolated_db.users.inject_on_insert = {
        "_id": "internal", "reset_token": "hidden", "mfa_secret": "hidden", "api_key": "hidden",
    }
    response = TestClient(server.app).post("/api/auth/signup", json={
        "email": "NEW.User@Example.com", "password": "long-enough-password", "name": "Test",
    })
    assert response.status_code == 200
    assert set(response.json()["user"]) == {"id", "email", "name", "role", "tenant_id", "created_at"}
    assert response.json()["user"]["email"] == "new.user@example.com"
    assert response.json()["user"]["role"] == "viewer"


def test_login_and_auth_me_allowlist_arbitrary_database_fields(isolated_db):
    password = bcrypt.hashpw(b"long-enough-password", bcrypt.gensalt()).decode()
    stored = {
        "id": "U1", "email": "user@example.com", "name": "User", "role": "viewer",
        "password": password, "active": True, "created_at": "2026-01-01",
        "reset_token": "hidden", "refresh_token": "hidden", "mfa_secret": "hidden",
        "api_credentials": "hidden", "security_metadata": {"hidden": True}, "unknown": "hidden",
    }
    isolated_db.users.docs = [stored]
    login = TestClient(server.app).post("/api/auth/login", json={
        "email": "user@example.com", "password": "long-enough-password",
    })
    assert login.status_code == 200
    assert set(login.json()["user"]) == {"id", "email", "name", "role", "active", "created_at"}

    database_check = authenticated_user_dependency(isolated_db, server.settings.jwt_secret)
    server.app.dependency_overrides[server.get_current_user] = database_check
    me = TestClient(server.app).get("/api/auth/me", headers={"Authorization": f"Bearer {login.json()['token']}"})
    assert me.status_code == 200
    assert set(me.json()) == {"id", "email", "name", "role", "active", "created_at"}


def test_signup_rejects_weak_password_invalid_email_and_case_insensitive_duplicate(isolated_db):
    client = TestClient(server.app)
    assert client.post("/api/auth/signup", json={
        "email": "valid@example.com", "password": "short", "name": "Test"
    }).status_code == 422
    assert client.post("/api/auth/signup", json={
        "email": "not-an-email", "password": "long-enough-password", "name": "Test"
    }).status_code == 422
    isolated_db.users.docs = [{"email": "Legacy.User@Example.com"}]
    assert client.post("/api/auth/signup", json={
        "email": "legacy.user@example.com", "password": "long-enough-password", "name": "Test"
    }).status_code == 400


def test_lowercase_login_supports_mixed_case_legacy_email(isolated_db):
    isolated_db.users.docs = [{
        "id": "U1", "email": "Legacy.User@Example.COM", "name": "Legacy", "role": "viewer",
        "password": bcrypt.hashpw(b"long-enough-password", bcrypt.gensalt()).decode(),
    }]
    response = TestClient(server.app).post("/api/auth/login", json={
        "email": "legacy.user@example.com", "password": "long-enough-password",
    })
    assert response.status_code == 200


def test_regex_special_characters_cannot_expand_legacy_lookup(isolated_db):
    isolated_db.users.docs = [{
        "id": "U1", "email": "userXtag@example.com", "name": "Other", "role": "viewer",
        "password": bcrypt.hashpw(b"long-enough-password", bcrypt.gensalt()).decode(),
    }]
    response = TestClient(server.app).post("/api/auth/login", json={
        "email": "user+tag@example.com", "password": "long-enough-password",
    })
    assert response.status_code == 401


@pytest.mark.parametrize("stored", [pytest.param("missing", id="missing"), None, 123, "not-a-bcrypt-hash"])
def test_login_handles_malformed_stored_password_as_401(isolated_db, stored):
    user = {"id": "U1", "email": "user@example.com", "name": "User", "role": "viewer"}
    if stored != "missing":
        user["password"] = stored
    isolated_db.users.docs = [user]
    response = TestClient(server.app).post("/api/auth/login", json={
        "email": "user@example.com", "password": "long-enough-password",
    })
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


@pytest.mark.parametrize("state", ["missing", "inactive"])
def test_auth_me_rejects_unavailable_database_user(state):
    token_user = {"id": "U1", "email": "user@example.com", "name": "User", "role": "owner"}
    docs = [] if state == "missing" else [{**token_user, "active": False, "password": "hidden"}]
    database_check = authenticated_user_dependency(FakeDB(users=docs), server.settings.jwt_secret)
    server.app.dependency_overrides[server.get_current_user] = database_check
    token = create_token(token_user, server.settings.jwt_secret)
    response = TestClient(server.app).get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_database_role_overrides_stale_token_role():
    token_user = {"id": "U1", "email": "old@example.com", "name": "User", "role": "owner"}
    current = {**token_user, "role": "viewer", "password": "hidden"}
    database_check = authenticated_user_dependency(FakeDB(users=[current]), server.settings.jwt_secret)
    server.app.dependency_overrides[server.get_current_user] = database_check
    token = create_token(token_user, server.settings.jwt_secret)
    client = TestClient(server.app, headers={"Authorization": f"Bearer {token}"})
    assert client.get("/api/auth/me").json()["role"] == "viewer"
    assert client.post("/api/loads", json={}).status_code == 403


def test_seed_disabled_and_owner_only(monkeypatch):
    as_role("owner")
    monkeypatch.setattr(server, "settings", replace(server.settings, allow_seed_endpoint=False))
    assert TestClient(server.app).post("/api/seed").status_code == 403
    as_role("viewer")
    monkeypatch.setattr(server, "settings", replace(server.settings, allow_seed_endpoint=True, app_env="test"))
    assert TestClient(server.app).post("/api/seed?force=true").status_code == 403


def test_development_force_seed_passes_configuration_gate_without_executing_seed(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(
        server.settings, allow_seed_endpoint=True, app_env="  DeVeLoPmEnT  "))
    assert server.enforce_seed_config(force=True) is None


@pytest.mark.parametrize("app_env", ["production", "prod", "staging", "stage", "unknown", "", "developmnt"])
def test_force_seed_fails_closed_outside_explicit_safe_environments(monkeypatch, app_env):
    monkeypatch.setattr(server, "settings", replace(
        server.settings, allow_seed_endpoint=True, app_env=app_env))
    with pytest.raises(HTTPException) as exc:
        server.enforce_seed_config(force=True)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("app_env", ["local", "development", "dev", "test", " TEST "])
def test_force_seed_safe_environment_allowlist(app_env):
    assert force_seed_allowed(app_env)


@pytest.mark.parametrize("secret", [None, "", "dev_secret", "too-short"])
def test_invalid_jwt_configuration_rejected(secret):
    with pytest.raises(RuntimeError):
        validate_jwt_secret(secret)


def test_valid_cors_origins_are_normalized_and_deduplicated():
    assert parse_cors_origins(
        " HTTP://LOCALHOST:3000/, https://Example.com,https://example.com/,http://127.0.0.1:8000 "
    ) == ["http://localhost:3000", "https://example.com", "http://127.0.0.1:8000"]
    assert parse_cors_origins("") == []


@pytest.mark.parametrize("origin", [
    "*", "https://*.example.com", "ftp://example.com", "http://", "https://",
    "http://user@example.com", "http://user:pass@example.com", "https://example.com/path",
    "https://example.com?query=1", "https://example.com#fragment", "https://example.com:bad",
    "https://example.com:70000", "https://bad host.example", "https://-bad.example",
])
def test_invalid_cors_origins_are_rejected(origin):
    with pytest.raises(RuntimeError):
        parse_cors_origins(origin)
