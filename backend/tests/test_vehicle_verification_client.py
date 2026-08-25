"""
Isolated tests for the Metaphora Verify vehicle (VIN) client — structural
mirror of test_party_verification_client.py: no FakeDB, no TestClient, just
httpx.MockTransport to control what the "server" returns.
"""
import httpx
import pytest
from dataclasses import dataclass

from app.infrastructure import vehicle_verification_client as vvc


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
    monkeypatch.setattr(vvc.httpx, "AsyncClient", _fake_async_client)


@pytest.mark.anyio
async def test_not_configured_returns_none_without_a_call(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"assessment": {}})
    _client_with_transport(handler, monkeypatch)
    settings = _Settings(metaphora_verify_base_url=None)
    result = await vvc.fetch_vehicle_verification(settings, "1FUJGHDV8CLBP8045")
    assert result is None and calls == []


@pytest.mark.anyio
async def test_no_vin_returns_none_without_a_call(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"assessment": {}})
    _client_with_transport(handler, monkeypatch)
    settings = _Settings()
    result = await vvc.fetch_vehicle_verification(settings, None)
    assert result is None and calls == []
    result = await vvc.fetch_vehicle_verification(settings, "   ")
    assert result is None and calls == []


@pytest.mark.anyio
async def test_success_wraps_assessment_with_ok_status(monkeypatch):
    def handler(request):
        assert request.headers["x-metaphora-service-key"] == "mcvsk_test"
        assert request.url.path == "/api/verify-vehicle/1FUJGHDV8CLBP8045"
        return httpx.Response(200, json={"assessment": {
            "risk_level": "Green", "vin_valid_checksum": True,
            "plausible_freight_vehicle": True,
        }})
    _client_with_transport(handler, monkeypatch)
    settings = _Settings()
    result = await vvc.fetch_vehicle_verification(settings, "1FUJGHDV8CLBP8045")
    assert result == {"status": "ok", "risk_level": "Green",
                       "vin_valid_checksum": True, "plausible_freight_vehicle": True}


@pytest.mark.anyio
async def test_non_200_returns_unavailable_status(monkeypatch):
    # Unlike the broker client, there is no "not_found" branch here — NHTSA
    # vPIC never 404s, so every non-200 collapses to "unavailable".
    def handler(request):
        return httpx.Response(404)
    _client_with_transport(handler, monkeypatch)
    settings = _Settings()
    result = await vvc.fetch_vehicle_verification(settings, "1FUJGHDV8CLBP8045")
    assert result == {"status": "unavailable"}


@pytest.mark.anyio
async def test_5xx_returns_unavailable_status(monkeypatch):
    def handler(request):
        return httpx.Response(502)
    _client_with_transport(handler, monkeypatch)
    settings = _Settings()
    result = await vvc.fetch_vehicle_verification(settings, "1FUJGHDV8CLBP8045")
    assert result == {"status": "unavailable"}


@pytest.mark.anyio
async def test_timeout_returns_unavailable_status(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("timed out")
    _client_with_transport(handler, monkeypatch)
    settings = _Settings()
    result = await vvc.fetch_vehicle_verification(settings, "1FUJGHDV8CLBP8045")
    assert result == {"status": "unavailable"}
