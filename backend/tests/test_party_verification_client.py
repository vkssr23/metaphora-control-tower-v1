"""
Isolated tests for the Metaphora Verify outbound client — no FakeDB, no
TestClient, just httpx.MockTransport (already ships with httpx, no new
dependency) to control what the "server" returns.
"""
import httpx
import pytest
from dataclasses import dataclass

from app.infrastructure import party_verification_client as pvc


@dataclass
class _Settings:
    metaphora_verify_base_url: str | None = "https://verify.example.test"
    metaphora_verify_service_key: str | None = "mcvsk_test"
    metaphora_verify_timeout_seconds: float = 5.0


RATE_WITH_MC = {"accepted_snapshot": {"extracted_fields": {"broker_mc": "MC123"}}}
RATE_NO_MC = {"accepted_snapshot": {"extracted_fields": {}}}


_RealAsyncClient = httpx.AsyncClient


def _client_with_transport(settings, handler, monkeypatch):
    def _fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)
    monkeypatch.setattr(pvc.httpx, "AsyncClient", _fake_async_client)


@pytest.mark.anyio
async def test_not_configured_returns_none_without_a_call(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"assessment": {}})
    _client_with_transport(None, handler, monkeypatch)
    settings = _Settings(metaphora_verify_base_url=None)
    result = await pvc.fetch_broker_verification(settings, RATE_WITH_MC)
    assert result is None and calls == []


@pytest.mark.anyio
async def test_no_broker_mc_returns_none_without_a_call(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"assessment": {}})
    _client_with_transport(None, handler, monkeypatch)
    settings = _Settings()
    result = await pvc.fetch_broker_verification(settings, RATE_NO_MC)
    assert result is None and calls == []


@pytest.mark.anyio
async def test_success_wraps_assessment_with_ok_status(monkeypatch):
    def handler(request):
        assert request.headers["x-metaphora-service-key"] == "mcvsk_test"
        assert request.url.path == "/api/verify-broker/MC123"
        return httpx.Response(200, json={"assessment": {"risk_level": "Green", "broker_authority_status": "A"}})
    _client_with_transport(None, handler, monkeypatch)
    settings = _Settings()
    result = await pvc.fetch_broker_verification(settings, RATE_WITH_MC)
    assert result == {"status": "ok", "risk_level": "Green", "broker_authority_status": "A"}


@pytest.mark.anyio
async def test_404_returns_not_found_status(monkeypatch):
    def handler(request):
        return httpx.Response(404, json={"detail": "not found"})
    _client_with_transport(None, handler, monkeypatch)
    settings = _Settings()
    result = await pvc.fetch_broker_verification(settings, RATE_WITH_MC)
    assert result == {"status": "not_found"}


@pytest.mark.anyio
async def test_5xx_returns_unavailable_status(monkeypatch):
    def handler(request):
        return httpx.Response(502)
    _client_with_transport(None, handler, monkeypatch)
    settings = _Settings()
    result = await pvc.fetch_broker_verification(settings, RATE_WITH_MC)
    assert result == {"status": "unavailable"}


@pytest.mark.anyio
async def test_timeout_returns_unavailable_status(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("timed out")
    _client_with_transport(None, handler, monkeypatch)
    settings = _Settings()
    result = await pvc.fetch_broker_verification(settings, RATE_WITH_MC)
    assert result == {"status": "unavailable"}
