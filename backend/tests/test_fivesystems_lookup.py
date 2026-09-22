"""Tests for the live 5Systems plate-lookup module - see
app/services/fivesystems_client.py's module docstring for what this is and
why. All HTTP is mocked (httpx.MockTransport, same pattern as
test_yandex_relay.py) - never hits the real api.5systems.ru."""

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.models.work_order import WorkOrder
from app.services import fivesystems_client, planner_service
from app.services.fivesystems_client import FiveSystemsError

PLANNER_URL = "/api/v1/planner"

COMPANY_UUID = "fef76279-0964-4918-9bf7-58537dd06943"
CAR_UUID = "aafaf61c-57c0-11ef-bd37-d7363aa7cb14"
AGENT_UUID = "aafaf61b-57c0-11ef-bd37-d7363aa7cb14"


def test_normalize_plate_maps_latin_lookalikes_and_uppercases() -> None:
    # "x669me777" typed on a Latin keyboard layout for "Х669МЕ777".
    assert fivesystems_client._normalize_plate("x669me777") == "Х669МЕ777"
    assert fivesystems_client._normalize_plate("  Х669МЕ777  ") == "Х669МЕ777"


@pytest.fixture(autouse=True)
def _reset_token_cache():
    # The module caches a token at module scope (see its docstring for why) -
    # tests must not leak a cached token/expiry between each other.
    fivesystems_client._cached_token = None
    fivesystems_client._cached_token_expires_at = 0.0
    yield
    fivesystems_client._cached_token = None
    fivesystems_client._cached_token_expires_at = 0.0


def _make_mock_transport(calls: list[str], *, agent_found: bool = True) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")

        if request.url.path == "/auth/v1/oidc/login":
            return httpx.Response(
                200,
                json={"access_token": "test-token", "expires_in": 3600, "refresh_token": "r"},
            )

        if request.url.path == "/dataset/v1/production/document":
            code = request.url.params.get("code")
            if code != "Х669МЕ777":
                return httpx.Response(200, json={"data": [], "pagination": {"total_count": 0}})
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "uuid": "35578c1d-b5d7-11f1-bd4b-e20fc4e9405c",
                            "general_params": {
                                "number": "ПС00010256",
                                "date": "2026-09-21T19:11:35+03:00",
                            },
                            "type": "ЗАКАЗ_НАРЯД",
                            "agent_uuid": AGENT_UUID,
                            "car_uuid": CAR_UUID,
                        }
                    ],
                    "pagination": {"total_count": 1},
                },
            )

        if request.url.path == "/dataset/v1/car":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "uuid": CAR_UUID,
                            "name": "BMW X6 № Х669МЕ777 VIN X4XFG211700G85936",
                            "vin": "X4XFG211700G85936",
                            "reg_num": "Х669МЕ777",
                        }
                    ]
                },
            )

        if request.url.path == "/dataset/v1/agent":
            if not agent_found:
                return httpx.Response(200, json={"data": []})
            return httpx.Response(
                200, json={"data": [{"uuid": AGENT_UUID, "full_name": "Богданович Борис Юрьевич"}]}
            )

        if request.url.path == "/export/v1/order/search":
            return httpx.Response(
                200,
                json=[
                    {
                        "order_id": "x",
                        "doc_number": "10256",
                        "doc_date": "2026-09-21T19:11:35Z",
                        "doc_sum": {"operations": 6000, "parts": 0, "total": 6000},
                    }
                ],
            )

        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _patch_client(monkeypatch, transport: httpx.MockTransport) -> None:
    class _MockedClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _MockedClient)


def _configure_settings(monkeypatch) -> None:
    settings = fivesystems_client.get_settings()
    monkeypatch.setattr(settings, "fivesystems_username", "API_User")
    monkeypatch.setattr(settings, "fivesystems_password", "test-password")
    monkeypatch.setattr(settings, "fivesystems_company_uuid", COMPANY_UUID)
    monkeypatch.setattr(settings, "enable_fivesystems_lookup", True)


def test_lookup_work_order_by_plate_full_flow(monkeypatch) -> None:
    calls: list[str] = []
    _patch_client(monkeypatch, _make_mock_transport(calls))
    _configure_settings(monkeypatch)

    result = fivesystems_client.lookup_work_order_by_plate("x669me777")

    assert result is not None
    assert result.external_number == "ПС00010256"
    assert result.vehicle_description == "BMW X6 № Х669МЕ777 VIN X4XFG211700G85936"
    assert result.vin == "X4XFG211700G85936"
    assert result.plate == "Х669МЕ777"
    assert result.customer_name == "Богданович Борис Юрьевич"
    assert result.amount == Decimal("6000")
    # One auth call reused across every subsequent request, not one per call.
    assert calls.count("POST /auth/v1/oidc/login") == 1
    assert "GET /dataset/v1/production/document" in calls
    assert "POST /dataset/v1/car" in calls
    assert "POST /dataset/v1/agent" in calls


def test_lookup_work_order_by_plate_not_found_returns_none(monkeypatch) -> None:
    _patch_client(monkeypatch, _make_mock_transport([]))
    _configure_settings(monkeypatch)

    result = fivesystems_client.lookup_work_order_by_plate("А000АА000")

    assert result is None


def test_lookup_survives_amount_lookup_failure(monkeypatch) -> None:
    """The export/v1 amount lookup is explicitly best-effort - a broken
    response there must not fail the whole lookup, which already has
    everything it needs from dataset/v1 alone."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1/oidc/login":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if request.url.path == "/dataset/v1/production/document":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "general_params": {
                                "number": "ПС00010256",
                                "date": "2026-09-21T19:11:35+03:00",
                            },
                            "agent_uuid": AGENT_UUID,
                            "car_uuid": CAR_UUID,
                        }
                    ]
                },
            )
        if request.url.path == "/dataset/v1/car":
            return httpx.Response(
                200, json={"data": [{"name": "BMW X6", "vin": "X4XFG211700G85936"}]}
            )
        if request.url.path == "/dataset/v1/agent":
            return httpx.Response(200, json={"data": [{"full_name": "Тест Тестов"}]})
        if request.url.path == "/export/v1/order/search":
            return httpx.Response(500, text="internal error")
        return httpx.Response(404)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    _configure_settings(monkeypatch)

    result = fivesystems_client.lookup_work_order_by_plate("Х669МЕ777")

    assert result is not None
    assert result.amount is None


def test_lookup_raises_on_missing_credentials(monkeypatch) -> None:
    settings = fivesystems_client.get_settings()
    monkeypatch.setattr(settings, "fivesystems_username", None)
    monkeypatch.setattr(settings, "fivesystems_company_uuid", COMPANY_UUID)

    with pytest.raises(FiveSystemsError):
        fivesystems_client.lookup_work_order_by_plate("Х669МЕ777")


# ---- Endpoint + get_or_create_stub_work_order --------------------------------


def test_lookup_endpoint_disabled_returns_503(client, auth_headers, monkeypatch) -> None:
    settings = fivesystems_client.get_settings()
    monkeypatch.setattr(settings, "enable_fivesystems_lookup", False)

    response = client.get(
        f"{PLANNER_URL}/work-orders/lookup-by-plate",
        params={"plate": "Х669МЕ777"},
        headers=auth_headers,
    )

    assert response.status_code == 503


def test_lookup_endpoint_not_found_returns_404(client, auth_headers, monkeypatch) -> None:
    _patch_client(monkeypatch, _make_mock_transport([]))
    _configure_settings(monkeypatch)

    response = client.get(
        f"{PLANNER_URL}/work-orders/lookup-by-plate",
        params={"plate": "А000АА000"},
        headers=auth_headers,
    )

    assert response.status_code == 404


def test_lookup_endpoint_creates_work_order_and_is_idempotent(
    client, auth_headers, monkeypatch, db_session
) -> None:
    calls: list[str] = []
    _patch_client(monkeypatch, _make_mock_transport(calls))
    _configure_settings(monkeypatch)

    first = client.get(
        f"{PLANNER_URL}/work-orders/lookup-by-plate",
        params={"plate": "x669me777"},
        headers=auth_headers,
    )
    assert first.status_code == 200
    body = first.json()
    assert body["external_number"] == "ПС00010256"
    assert body["customer_name"] == "Богданович Борис Юрьевич"
    assert Decimal(str(body["amount"])) == Decimal("6000")

    rows = (
        db_session.execute(select(WorkOrder).where(WorkOrder.external_number == "ПС00010256"))
        .scalars()
        .all()
    )
    assert len(rows) == 1

    # A real import having since populated the row must never be clobbered
    # by a second live lookup for the same plate.
    rows[0].customer_name = "Реальные данные из 1С"
    rows[0].amount = Decimal("12345")
    db_session.commit()

    second = client.get(
        f"{PLANNER_URL}/work-orders/lookup-by-plate",
        params={"plate": "x669me777"},
        headers=auth_headers,
    )
    assert second.status_code == 200
    assert second.json()["customer_name"] == "Реальные данные из 1С"
    assert Decimal(str(second.json()["amount"])) == Decimal("12345")

    rows_after = (
        db_session.execute(select(WorkOrder).where(WorkOrder.external_number == "ПС00010256"))
        .scalars()
        .all()
    )
    assert len(rows_after) == 1


def test_get_or_create_stub_work_order_defaults_amount_to_zero(db_session) -> None:
    from datetime import UTC, datetime

    result = fivesystems_client.WorkOrderLookupResult(
        external_number="ПС00099999",
        document_date=datetime(2026, 9, 22, tzinfo=UTC),
        vehicle_description="Kia Rio",
        vin=None,
        plate="А123ВС77",
        customer_name=None,
        amount=None,
    )

    work_order = planner_service.get_or_create_stub_work_order(db_session, result)

    assert work_order.amount == Decimal("0")
    assert work_order.source_system == "alpha-auto"
