"""
Isolated tests for the Metaphora Verify SSO redemption client — no FakeDB,
no TestClient, just httpx.MockTransport, mirroring
test_party_verification_client.py's exact pattern.
"""
import httpx
import pytest
from dataclasses import dataclass

from app.infrastructure import verify_sso_client as vsc


@dataclass
class _Settings:
    metaphora_verify_base_url: str | None = "https://verify.example.test"
    metaphora_verify_service_key: str | None = "mcvsk_test"
    metaphora_verify_timeout_seconds: float = 5.0


_RealAsyncClient = httpx.AsyncClient


def _client_with_transport(handler, monkeypatch):
    def _fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)
    monkeypatch.setattr(vsc.httpx, "AsyncClient", _fake_async_client)


@pytest.mark.anyio
async def test_not_configured_returns_none_without_a_call(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})
    _client_with_transport(handler, monkeypatch)
    settings = _Settings(metaphora_verify_base_url=None)
    result = await vsc.redeem_sso_code(settings, "some-code")
    assert result is None and calls == []


@pytest.mark.anyio
async def test_no_code_returns_none_without_a_call(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})
    _client_with_transport(handler, monkeypatch)
    settings = _Settings()
    result = await vsc.redeem_sso_code(settings, "")
    assert result is None and calls == []


@pytest.mark.anyio
async def test_success_wraps_identity_with_ok_status(monkeypatch):
    def handler(request):
        assert request.headers["x-metaphora-service-key"] == "mcvsk_test"
        assert request.url.path == "/api/auth/sso/redeem-code"
        return httpx.Response(200, json={
            "user_id": 7, "org_id": 42, "org_name": "Acme Freight",
            "email": "owner@example.com", "role": "admin", "email_verified": True,
        })
    _client_with_transport(handler, monkeypatch)
    settings = _Settings()
    result = await vsc.redeem_sso_code(settings, "abc")
    assert result == {"status": "ok", "user_id": 7, "org_id": 42, "org_name": "Acme Freight",
                       "email": "owner@example.com", "role": "admin", "email_verified": True}


@pytest.mark.anyio
async def test_400_returns_invalid_or_expired_status(monkeypatch):
    def handler(request):
        return httpx.Response(400, json={"detail": "Sign-in code is invalid or has expired"})
    _client_with_transport(handler, monkeypatch)
    settings = _Settings()
    result = await vsc.redeem_sso_code(settings, "abc")
    assert result == {"status": "invalid_or_expired"}


@pytest.mark.anyio
async def test_5xx_returns_unavailable_status(monkeypatch):
    def handler(request):
        return httpx.Response(502)
    _client_with_transport(handler, monkeypatch)
    settings = _Settings()
    result = await vsc.redeem_sso_code(settings, "abc")
    assert result == {"status": "unavailable"}


@pytest.mark.anyio
async def test_timeout_returns_unavailable_status(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("timed out")
    _client_with_transport(handler, monkeypatch)
    settings = _Settings()
    result = await vsc.redeem_sso_code(settings, "abc")
    assert result == {"status": "unavailable"}
