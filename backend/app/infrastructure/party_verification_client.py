"""
Outbound client for Metaphora Verify's broker-authority/fraud-signal check
(GET /api/verify-broker/{mc}?id_type=mc). The only direct HTTP client in
this codebase — see config.py for why its settings are optional unlike
this app's other fail-closed config. Mirrors demo_routes.py's ai_chat
lazy-config + try/except + graceful-degrade shape, applied to a plain
httpx call instead of an SDK import.

fetch_broker_verification() never raises — callers always get back either
None (not attempted: not configured, or no broker_mc to check) or a dict
tagged with a "status" the domain layer switches on. Treat every
non-"ok" status as "no independently confirmed signal", never as "broker
is clean".
"""
import logging

import httpx

logger = logging.getLogger(__name__)


def is_configured(settings) -> bool:
    return bool(settings.metaphora_verify_base_url and settings.metaphora_verify_service_key)


async def fetch_broker_verification(settings, rate: dict | None) -> dict | None:
    fields = (rate or {}).get("accepted_snapshot", {}).get("extracted_fields", {}) or {}
    mc = fields.get("broker_mc")
    if not mc or not is_configured(settings):
        return None

    url = f"{settings.metaphora_verify_base_url}/api/verify-broker/{mc}"
    headers = {"X-Metaphora-Service-Key": settings.metaphora_verify_service_key}
    try:
        async with httpx.AsyncClient(timeout=settings.metaphora_verify_timeout_seconds) as client:
            response = await client.get(url, params={"id_type": "mc"}, headers=headers)
    except httpx.HTTPError:
        logger.error("Metaphora Verify request failed for broker mc=%s", mc)
        return {"status": "unavailable"}

    if response.status_code == 404:
        return {"status": "not_found"}
    if response.status_code != 200:
        logger.error("Metaphora Verify returned %s for broker mc=%s", response.status_code, mc)
        return {"status": "unavailable"}
    return {"status": "ok", **response.json()["assessment"]}
