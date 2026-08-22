"""
Outbound client for Metaphora Verify's VIN-decode/validity check
(GET /api/verify-vehicle/{vin}). Mirrors party_verification_client.py's
shape exactly, but takes a bare VIN string — the caller already has
truck.get("vin") in hand, no nested extraction step needed.

fetch_vehicle_verification() never raises — callers always get back either
None (not attempted: not configured, or no VIN to check) or a dict tagged
with a "status" the domain layer switches on. Treat every non-"ok" status
as "no independently confirmed signal", never as "vehicle is fine".

Simpler than fetch_broker_verification(): NHTSA's vPIC endpoint never 404s
(confirmed by direct probing — see Metaphora Verify's nhtsa_client.py), so
there's no separate "not_found" branch; every non-200 collapses to
"unavailable".
"""
import logging

import httpx

logger = logging.getLogger(__name__)


def is_configured(settings) -> bool:
    return bool(settings.metaphora_verify_base_url and settings.metaphora_verify_service_key)


async def fetch_vehicle_verification(settings, vin: str | None) -> dict | None:
    vin = (vin or "").strip()
    if not vin or not is_configured(settings):
        return None

    url = f"{settings.metaphora_verify_base_url}/api/verify-vehicle/{vin}"
    headers = {"X-Metaphora-Service-Key": settings.metaphora_verify_service_key}
    try:
        async with httpx.AsyncClient(timeout=settings.metaphora_verify_timeout_seconds) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError:
        logger.error("Metaphora Verify request failed for vin=%s", vin)
        return {"status": "unavailable"}

    if response.status_code != 200:
        logger.error("Metaphora Verify returned %s for vin=%s", response.status_code, vin)
        return {"status": "unavailable"}
    return {"status": "ok", **response.json()["assessment"]}
