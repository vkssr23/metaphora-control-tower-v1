"""Regression tests: no demo logins, signup + login flow works."""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://metaphora-backend-staging-certification.up.railway.app").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def unique_email():
    return f"qa_{int(time.time()*1000)}@test.com"


# ---- Regression: demo users must be gone ----
@pytest.mark.parametrize("email,pw", [
    ("owner@dispatch.com", "owner123"),
    ("dispatcher@dispatch.com", "dispatch123"),
    ("finance@dispatch.com", "finance123"),
])
def test_demo_logins_removed(client, email, pw):
    r = client.post(f"{API}/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 401, f"Expected 401 for {email}, got {r.status_code}: {r.text}"


# ---- Signup happy path ----
# Public signup can only ever create a "viewer" account (server-enforced,
# see test_security_patch.py::test_public_signup_rejects_privileged_roles) —
# this used to request "dispatcher" and got 403 for it.
def test_signup_returns_token_and_user(client, unique_email):
    r = client.post(f"{API}/auth/signup", json={
        "name": "QA User",
        "email": unique_email,
        "password": "testpass123456",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "token" in body and isinstance(body["token"], str) and len(body["token"]) > 0
    assert "user" in body
    assert body["user"]["email"] == unique_email
    assert body["user"]["role"] == "viewer"
    assert body["user"]["name"] == "QA User"
    assert "password" not in body["user"]


def test_login_after_signup(client, unique_email):
    r = client.post(f"{API}/auth/login", json={"email": unique_email, "password": "testpass123456"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "token" in body
    assert body["user"]["email"] == unique_email


def test_signup_duplicate_email_returns_400(client, unique_email):
    r = client.post(f"{API}/auth/signup", json={
        "name": "Dup", "email": unique_email, "password": "testpass123456"
    })
    assert r.status_code == 400
    assert "exists" in r.text.lower()


def test_login_wrong_password_returns_401(client, unique_email):
    r = client.post(f"{API}/auth/login", json={"email": unique_email, "password": "wrongpass"})
    assert r.status_code == 401
