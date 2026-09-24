"""Optional module: live 5Systems (Alpha-Auto) lookup by vehicle plate.

Why this exists: the 1C export now runs once a day (see 1c/TestExportOrders.bsl
and DEPLOYMENT.md - it moved off a 30-minute schedule because that still held
a 1C user license/session for hours at a time with nobody able to grant "log
on as a batch job" on the RDP host). A work order created in Alpha-Auto today
therefore will not exist in this backend's own `work_orders` table until
tomorrow morning's import. This module lets the Planner look one up directly
from 5Systems' own hosted REST API (api.5systems.ru - unrelated to the 1C
export path entirely) by vehicle plate, so an operator scheduling today's car
does not have to wait until the next day.

Two 5Systems API surfaces were explored (see chat history, not reproduced
here) and only one turned out to expose what's needed:

- `export/v1` (the one Alpha-Auto/1C is publicly documented as offering) only
  returns the document number as a bare digit string ("10255"), never the
  ПС00010255-style number this whole product keys work orders by. 5Systems
  support confirmed this is intentional on their end (their own uniqueness
  guarantee is `order_id`, not the printed number) and that per-department
  prefixes are not fixed, so the printed number cannot be reconstructed from
  the bare one.
- `dataset/v1` (a lower-level, UUID-heavy surface, undocumented for this
  integration until now) exposes the real thing directly:
  `general_params.number` on `GET /production/document` IS the full
  "ПС00010255"-style number. Confirmed against real data. This module uses
  `dataset/v1` exclusively for identity/vehicle/customer data, and only
  falls back to `export/v1/order/search` - best-effort, failure tolerated -
  for `doc_sum.total`, which `dataset/v1` does not expose.

`production/document` is explicitly scoped to *in-production* (open/active)
work orders - a closed/historical one will not be found here, which is
exactly right for this use case (a just-created order the nightly export
has not reached yet is, by definition, still open) and exactly wrong for
anything else - do not reuse this module as a general "look up any work
order" path.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import structlog

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 15.0
# Re-authenticate this much before the token's own reported expiry, so a
# request never starts with a token that's about to (or just did) expire.
TOKEN_REFRESH_MARGIN_SECONDS = 60


class FiveSystemsError(Exception):
    """Raised when 5Systems can't be reached, rejects the request, or
    returns something this integration doesn't know how to use. Callers
    (the API endpoint) turn this into a clean error for the operator - it
    is never allowed to look like "no order found" (see the None-return
    convention on lookup_work_order_by_plate)."""


@dataclass
class WorkOrderLookupResult:
    external_number: str
    document_date: datetime
    vehicle_description: str | None
    vin: str | None
    plate: str | None
    customer_name: str | None
    amount: Decimal | None
    # Best-effort, from the separate /exr/{user_id} lookup below - only
    # available when production/document included a user_id (not always
    # present). Deliberately never written to WorkOrder.phone itself (see
    # planner_service.get_or_create_stub_work_order) - only ever used to
    # prefill a Planner record, same as vehicle/VIN/client here; the real
    # WorkOrder.phone still comes only from the next real 1C import.
    phone: str | None = None


# Module-level, not per-request - the token is reused across calls/requests
# for its own lifetime (5Systems' own login response - see the module
# docstring's history - reported values from 1h to 24h across different
# checks, so this reads whatever `expires_in` the response actually says
# rather than assuming a fixed duration). The backend runs as a single
# uvicorn process (no --workers - see DEPLOYMENT.md), so a plain module
# global guarded by one lock is enough; this is not meant to survive a
# multi-process deployment without revisiting.
_token_lock = threading.Lock()
_cached_token: str | None = None
_cached_token_expires_at: float = 0.0

# Plates are routinely typed on a Latin keyboard layout - these 12 Cyrillic
# letters (the only ones used on Russian plates) have Latin lookalikes that
# are visually identical but a different character to the API.
_LATIN_TO_CYRILLIC_PLATE = str.maketrans(
    {
        "A": "А",
        "B": "В",
        "E": "Е",
        "K": "К",
        "M": "М",
        "H": "Н",
        "O": "О",
        "P": "Р",
        "C": "С",
        "T": "Т",
        "Y": "У",
        "X": "Х",
    }
)


def _normalize_plate(plate: str) -> str:
    return plate.strip().upper().translate(_LATIN_TO_CYRILLIC_PLATE)


def _fetch_token(settings: Settings) -> tuple[str, float]:
    if not settings.fivesystems_username or not settings.fivesystems_password:
        raise FiveSystemsError("5Systems username/password are not configured")

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.post(
                f"{settings.fivesystems_api_base_url}/auth/v1/oidc/login",
                json={
                    "username": settings.fivesystems_username,
                    "password": settings.fivesystems_password,
                },
                headers={"accept": "application/json"},
            )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise FiveSystemsError(f"5Systems auth request failed: {exc}") from exc

    token = data.get("access_token")
    if not token:
        raise FiveSystemsError("5Systems auth response had no access_token")

    expires_in = data.get("expires_in")
    if not isinstance(expires_in, int | float) or expires_in <= 0:
        expires_in = 3600
    expires_at = time.monotonic() + max(expires_in - TOKEN_REFRESH_MARGIN_SECONDS, 30)
    return token, expires_at


def _get_token(settings: Settings, *, force_refresh: bool = False) -> str:
    global _cached_token, _cached_token_expires_at
    with _token_lock:
        if not force_refresh and _cached_token and time.monotonic() < _cached_token_expires_at:
            return _cached_token
        token, expires_at = _fetch_token(settings)
        _cached_token = token
        _cached_token_expires_at = expires_at
        return token


def _authed_request(
    settings: Settings,
    method: str,
    path: str,
    *,
    params: dict[str, str],
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    token = _get_token(settings)
    url = f"{settings.fivesystems_api_base_url}{path}"
    kwargs: dict[str, Any] = {
        "params": params,
        "headers": {"Authorization": f"Bearer {token}", "accept": "application/json"},
    }
    if json_body is not None:
        kwargs["json"] = json_body

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise FiveSystemsError(f"5Systems request to {path} failed: {exc}") from exc

    if response.status_code == 401:
        # The cached token may have just expired server-side even though our
        # own margin thought it was still good - one forced-refresh retry
        # before giving up, rather than surfacing a spurious failure.
        token = _get_token(settings, force_refresh=True)
        kwargs["headers"]["Authorization"] = f"Bearer {token}"
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise FiveSystemsError(f"5Systems request to {path} failed: {exc}") from exc

    if response.status_code >= 400:
        raise FiveSystemsError(
            f"5Systems {method} {path} returned {response.status_code}: {response.text[:300]}"
        )
    return response


def _search_active_document(settings: Settings, plate: str) -> dict[str, Any] | None:
    response = _authed_request(
        settings,
        "GET",
        "/dataset/v1/production/document",
        params={"company_uuid": settings.fivesystems_company_uuid or "", "code": plate},
    )
    items = response.json().get("data") or []
    if not items:
        return None
    # If a plate somehow has more than one open document, the operator
    # scheduling today's car almost certainly means the newest one.
    return max(items, key=lambda item: item.get("general_params", {}).get("date") or "")


def _get_car(settings: Settings, car_uuid: str) -> dict[str, Any] | None:
    response = _authed_request(
        settings,
        "POST",
        "/dataset/v1/car",
        params={"company_uuid": settings.fivesystems_company_uuid or ""},
        json_body={"uuid": [car_uuid]},
    )
    items = response.json().get("data") or []
    return items[0] if items else None


def _get_agent(settings: Settings, agent_uuid: str) -> dict[str, Any] | None:
    response = _authed_request(
        settings,
        "POST",
        "/dataset/v1/agent",
        params={"company_uuid": settings.fivesystems_company_uuid or ""},
        json_body={"uuid": [agent_uuid]},
    )
    items = response.json().get("data") or []
    return items[0] if items else None


def _search_amount(settings: Settings, plate: str) -> Decimal | None:
    """Best-effort only, via the *other* 5Systems API surface (export/v1) -
    see the module docstring for why dataset/v1 (used for everything else
    in this module) doesn't have a sum. Any failure here - not found,
    unexpected shape, network error - must not fail the whole lookup; the
    amount is a nice-to-have that self-heals from the next real 1C import
    regardless (see planner_service.get_or_create_stub_work_order)."""
    try:
        response = _authed_request(
            settings,
            "GET",
            "/export/v1/order/search",
            params={"company_uuid": settings.fivesystems_company_uuid or "", "reg_num": plate},
        )
        results = response.json()
        if not results:
            return None
        best = max(results, key=lambda r: r.get("doc_date") or "")
        total = best.get("doc_sum", {}).get("total")
        if total is None:
            return None
        return Decimal(str(total))
    except (FiveSystemsError, InvalidOperation, TypeError, KeyError, AttributeError) as exc:
        logger.warning("fivesystems_amount_lookup_failed", plate=plate, error=str(exc))
        return None


def _get_user_phone(settings: Settings, user_id: str) -> str | None:
    """Best-effort only, same tolerance as _search_amount above - a
    production/document response doesn't always include a user_id at all,
    and even when it does, this lookup failing (404, empty phone list,
    network error) must not fail the whole plate lookup. Returns the first
    phone number in the response with "+" prepended (e.g. "79775911275" ->
    "+79775911275"), or None."""
    try:
        response = _authed_request(
            settings,
            "GET",
            f"/exr/{user_id}",
            params={"company_uuid": settings.fivesystems_company_uuid or ""},
        )
        phones = response.json().get("phone") or []
        if not phones or not phones[0]:
            return None
        return f"+{phones[0]}"
    except (FiveSystemsError, TypeError, KeyError, AttributeError, IndexError) as exc:
        logger.warning("fivesystems_user_phone_lookup_failed", user_id=user_id, error=str(exc))
        return None


def lookup_work_order_by_plate(plate: str) -> WorkOrderLookupResult | None:
    """Returns None when no *open* document matches this plate (a normal,
    expected outcome - it just means there's nothing for the Planner to
    prefill from yet), and raises FiveSystemsError for anything that means
    the lookup itself didn't work (bad credentials, network failure,
    unexpected response shape) - the API endpoint must tell these apart
    for the operator rather than reporting a real failure as "not found"."""
    settings = get_settings()
    if not settings.fivesystems_company_uuid:
        raise FiveSystemsError("5Systems company_uuid is not configured")

    normalized_plate = _normalize_plate(plate)
    document = _search_active_document(settings, normalized_plate)
    if document is None:
        return None

    general = document.get("general_params") or {}
    number = general.get("number")
    date_str = general.get("date")
    if not number or not date_str:
        raise FiveSystemsError("5Systems production/document response is missing number/date")

    car_uuid = document.get("car_uuid")
    agent_uuid = document.get("agent_uuid")
    user_id = document.get("user_id")
    car = _get_car(settings, car_uuid) if car_uuid else None
    agent = _get_agent(settings, agent_uuid) if agent_uuid else None
    # Not every document includes a user_id - only attempt this when it does.
    phone = _get_user_phone(settings, user_id) if user_id else None

    return WorkOrderLookupResult(
        external_number=number,
        document_date=datetime.fromisoformat(date_str),
        vehicle_description=(car or {}).get("name") or None,
        vin=(car or {}).get("vin") or None,
        plate=(car or {}).get("reg_num") or normalized_plate,
        customer_name=(agent or {}).get("full_name") or None,
        amount=_search_amount(settings, normalized_plate),
        phone=phone,
    )
