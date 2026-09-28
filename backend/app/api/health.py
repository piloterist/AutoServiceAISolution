"""Liveness endpoint, intentionally outside /api/v1 - used by orchestrators too."""

import httpx
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# TEMPORARY - diagnosing why this backend's outbound HTTPS to Zeon's API
# hangs at the TLS handshake (works fine from the operator's own network) -
# need this instance's real egress IP to check against Zeon's own IP
# allowlist, if it has one. Remove once that's resolved.
@router.get("/debug-egress-ip")
def debug_egress_ip() -> dict[str, str]:
    try:
        resp = httpx.get("https://api.ipify.org?format=json", timeout=10.0)
        return {"egress_ip": resp.json().get("ip", "unknown")}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
