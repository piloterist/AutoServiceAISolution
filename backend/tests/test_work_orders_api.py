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


def test_delete_work_order_requires_auth(client, db_session) -> None:
    work_order = _make_work_order(external_number="WO-DELETE-1")
    db_session.add(work_order)
    db_session.commit()

    response = client.delete(f"{LIST_URL}/{work_order.id}")

    assert response.status_code == 401


def test_delete_work_order_removes_it(client, db_session, auth_headers) -> None:
    work_order = _make_work_order(external_number="WO-DELETE-2")
    db_session.add(work_order)
    db_session.commit()
    work_order_id = work_order.id

    response = client.delete(f"{LIST_URL}/{work_order_id}", headers=auth_headers)
    assert response.status_code == 204

    list_response = client.get(LIST_URL, headers=auth_headers)
    numbers = {item["external_number"] for item in list_response.json()["items"]}
    assert "WO-DELETE-2" not in numbers


def test_delete_work_order_missing_returns_404(client, auth_headers) -> None:
    response = client.delete(
        f"{LIST_URL}/00000000-0000-0000-0000-000000000000", headers=auth_headers
    )

    assert response.status_code == 404


def test_list_work_orders_filters_by_department(client, db_session, auth_headers) -> None:
    db_session.add(_make_work_order(external_number="WO-BODY", department="Кузовной цех"))
    db_session.add(_make_work_order(external_number="WO-PAINT", department="Малярный цех"))
    db_session.commit()

    response = client.get(LIST_URL, headers=auth_headers, params={"departments": "Кузовной цех"})

    assert response.status_code == 200
    numbers = {item["external_number"] for item in response.json()["items"]}
    assert numbers == {"WO-BODY"}


def test_get_departments_returns_distinct_values(client, db_session, auth_headers) -> None:
    db_session.add(_make_work_order(external_number="WO-A", department="Кузовной цех"))
    db_session.add(_make_work_order(external_number="WO-B", department="Кузовной цех"))
    db_session.add(_make_work_order(external_number="WO-C", department="Малярный цех"))
    db_session.add(_make_work_order(external_number="WO-D", department=None))
    db_session.commit()

    response = client.get(f"{LIST_URL}/departments", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["departments"] == ["Кузовной цех", "Малярный цех"]


def test_department_summary_groups_and_sums(client, db_session, auth_headers) -> None:
    db_session.add(
        _make_work_order(
            external_number="WO-A", department="Кузовной цех", amount=Decimal("300.00")
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-B", department="Кузовной цех", amount=Decimal("200.00")
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-C", department="Малярный цех", amount=Decimal("100.00")
        )
    )
    db_session.add(_make_work_order(external_number="WO-NO-DEPT", department=None))
    db_session.commit()

    response = client.get(f"{LIST_URL}/summary/by-department", headers=auth_headers)

    assert response.status_code == 200
    items = {item["department"]: item for item in response.json()["items"]}
    assert set(items) == {"Кузовной цех", "Малярный цех"}
    assert items["Кузовной цех"]["total_amount"] == "500.00"
    assert items["Кузовной цех"]["work_order_count"] == 2
    assert items["Малярный цех"]["total_amount"] == "100.00"
