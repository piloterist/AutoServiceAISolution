"""Liveness endpoint, intentionally outside /api/v1 - used by orchestrators too."""

import socket
import ssl
import time

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# TEMPORARY - narrowing down where the connection to Zeon's API
# (z138.fpg.ru:443) actually dies: bare TCP connect vs the TLS handshake on
# top of it. Remove once resolved - see health.py git history for context.
@router.get("/debug-zeon-connect")
def debug_zeon_connect() -> dict[str, str]:
    host, port = "z138.fpg.ru", 443
    result: dict[str, str] = {}

    start = time.monotonic()
    try:
        sock = socket.create_connection((host, port), timeout=8.0)
        result["tcp_connect"] = f"ok in {time.monotonic() - start:.2f}s"
    except Exception as exc:  # noqa: BLE001
        result["tcp_connect"] = f"FAILED after {time.monotonic() - start:.2f}s: {exc!r}"
        return result

    start = time.monotonic()
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(sock, server_hostname=host) as tls_sock:
            result["tls_handshake"] = f"ok in {time.monotonic() - start:.2f}s"
            result["tls_version"] = tls_sock.version() or "unknown"
    except Exception as exc:  # noqa: BLE001
        result["tls_handshake"] = f"FAILED after {time.monotonic() - start:.2f}s: {exc!r}"
    finally:
        sock.close()

    return result
