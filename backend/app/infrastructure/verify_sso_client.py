"""
Outbound client for Metaphora Verify's cross-product SSO code redemption
(POST /api/auth/sso/redeem-code). Mirrors party_verification_client.py's
shape exactly — same module structure, same never-raises contract.

redeem_sso_code() never raises — callers get back None (not attempted: not
configured, or no code given) or a dict tagged with a "status" the caller
switches on. Unlike fetch_broker_verification/fetch_vehicle_verification, a
non-"ok" status here is fatal to the in-flight request — there is no
"degrade gracefully" option for identity itself.
"""
import logging

import httpx

logger = logging.getLogger(__name__)


def is_configured(settings) -> bool:
    return bool(settings.metaphora_verify_base_url and settings.metaphora_verify_service_key)


async def redeem_sso_code(settings, code: str) -> dict | None:
    if not code or not is_configured(settings):
        return None

    url = f"{settings.metaphora_verify_base_url}/api/auth/sso/redeem-code"
    headers = {"X-Metaphora-Service-Key": settings.metaphora_verify_service_key}
    try:
        async with httpx.AsyncClient(timeout=settings.metaphora_verify_timeout_seconds) as client:
            response = await client.post(url, json={"code": code}, headers=headers)
    except httpx.HTTPError:
        logger.error("Metaphora Verify SSO redemption request failed")
        return {"status": "unavailable"}

    if response.status_code == 400:
        return {"status": "invalid_or_expired"}
    if response.status_code != 200:
        logger.error("Metaphora Verify returned %s for SSO code redemption", response.status_code)
        return {"status": "unavailable"}
    return {"status": "ok", **response.json()}
