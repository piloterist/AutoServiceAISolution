from datetime import datetime
from decimal import Decimal

from app.models.work_order import WorkOrder

LIST_URL = "/api/v1/work-orders"
SUMMARY_URL = "/api/v1/work-orders/summary/monthly"


def _make_work_order(**overrides) -> WorkOrder:
    defaults = dict(
        external_number="WO-0001",
        source_system="alpha-auto",
        document_date=datetime(2026, 6, 15, 10, 0, 0),
        customer_name="Customer A",
        payer_name="Insurance Co",
        vehicle_description="VW TIGUAN",
        amount=Decimal("1000.00"),
    )
    defaults.update(overrides)
    return WorkOrder(**defaults)


def test_list_work_orders_requires_auth(client) -> None:
    response = client.get(LIST_URL)
    assert response.status_code == 401


def test_list_work_orders_returns_items(client, db_session, auth_headers) -> None:
    db_session.add(_make_work_order(external_number="WO-0001"))
    db_session.add(
        _make_work_order(
            external_number="WO-0002",
            document_date=datetime(2026, 7, 1, 9, 0, 0),
            payer_name=None,
        )
    )
    db_session.commit()

    response = client.get(LIST_URL, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    numbers = {item["external_number"] for item in body["items"]}
    assert numbers == {"WO-0001", "WO-0002"}
    wo2 = next(item for item in body["items"] if item["external_number"] == "WO-0002")
    assert wo2["payer_name"] is None


def test_list_work_orders_filters_by_date_range(client, db_session, auth_headers) -> None:
    db_session.add(_make_work_order(external_number="WO-JUNE", document_date=datetime(2026, 6, 10)))
    db_session.add(_make_work_order(external_number="WO-JULY", document_date=datetime(2026, 7, 10)))
    db_session.commit()

    response = client.get(
        LIST_URL,
        headers=auth_headers,
        params={"date_from": "2026-07-01T00:00:00", "date_to": "2026-08-01T00:00:00"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["external_number"] for item in body["items"]] == ["WO-JULY"]


def test_monthly_summary_groups_and_sums_by_month(client, db_session, auth_headers) -> None:
    db_session.add(
        _make_work_order(
            external_number="WO-1", document_date=datetime(2026, 6, 5), amount=Decimal("100.00")
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-2", document_date=datetime(2026, 6, 20), amount=Decimal("50.00")
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-3", document_date=datetime(2026, 7, 1), amount=Decimal("200.00")
        )
    )
    db_session.commit()

    response = client.get(SUMMARY_URL, headers=auth_headers)

    assert response.status_code == 200
    items = {item["month"]: item for item in response.json()["items"]}
    assert items["2026-06"]["work_order_count"] == 2
    assert items["2026-06"]["total_amount"] == "150.00"
    assert items["2026-07"]["work_order_count"] == 1
    assert items["2026-07"]["total_amount"] == "200.00"
