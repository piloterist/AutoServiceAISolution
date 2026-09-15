from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLaborLine, WorkOrderPartLine

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
            external_number="WO-1",
            document_date=datetime(2026, 6, 5),
            closed_date=datetime(2026, 6, 5),
            amount=Decimal("100.00"),
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-2",
            document_date=datetime(2026, 6, 20),
            closed_date=datetime(2026, 6, 20),
            amount=Decimal("50.00"),
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-3",
            document_date=datetime(2026, 7, 1),
            closed_date=datetime(2026, 7, 1),
            amount=Decimal("200.00"),
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


def test_monthly_summary_attributes_revenue_to_closed_month_not_created_month(
    client, db_session, auth_headers
) -> None:
    """Opened in June, closed in September -> counts as September revenue,
    not June's - the exact scenario the user described."""
    db_session.add(
        _make_work_order(
            external_number="WO-CROSS-MONTH",
            document_date=datetime(2026, 6, 15),
            closed_date=datetime(2026, 9, 10),
            amount=Decimal("1000.00"),
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-NOT-CLOSED-YET",
            document_date=datetime(2026, 6, 16),
            closed_date=None,
            amount=Decimal("9999.00"),
        )
    )
    db_session.commit()

    response = client.get(SUMMARY_URL, headers=auth_headers)

    assert response.status_code == 200
    items = {item["month"]: item for item in response.json()["items"]}
    assert "2026-06" not in items
    assert items["2026-09"]["work_order_count"] == 1
    assert items["2026-09"]["total_amount"] == "1000.00"


def test_monthly_summary_date_range_filters_by_closed_date(
    client, db_session, auth_headers
) -> None:
    db_session.add(
        _make_work_order(
            external_number="WO-CLOSED-JUNE",
            document_date=datetime(2026, 6, 1),
            closed_date=datetime(2026, 6, 5),
            amount=Decimal("100.00"),
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-CREATED-JUNE-CLOSED-SEPT",
            document_date=datetime(2026, 6, 1),
            closed_date=datetime(2026, 9, 5),
            amount=Decimal("200.00"),
        )
    )
    db_session.commit()

    response = client.get(
        SUMMARY_URL,
        headers=auth_headers,
        params={"date_from": "2026-09-01T00:00:00", "date_to": "2026-10-01T00:00:00"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["month"] for item in body["items"]] == ["2026-09"]
    assert body["items"][0]["total_amount"] == "200.00"


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
            external_number="WO-A",
            department="Кузовной цех",
            amount=Decimal("300.00"),
            closed_date=datetime(2026, 6, 5),
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-B",
            department="Кузовной цех",
            amount=Decimal("200.00"),
            closed_date=datetime(2026, 6, 6),
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-C",
            department="Малярный цех",
            amount=Decimal("100.00"),
            closed_date=datetime(2026, 6, 7),
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-NO-DEPT", department=None, closed_date=datetime(2026, 6, 8)
        )
    )
    db_session.commit()

    response = client.get(f"{LIST_URL}/summary/by-department", headers=auth_headers)

    assert response.status_code == 200
    items = {item["department"]: item for item in response.json()["items"]}
    assert set(items) == {"Кузовной цех", "Малярный цех"}
    assert items["Кузовной цех"]["total_amount"] == "500.00"
    assert items["Кузовной цех"]["work_order_count"] == 2
    assert items["Малярный цех"]["total_amount"] == "100.00"


def test_get_work_order_detail_requires_auth(client, db_session) -> None:
    work_order = _make_work_order(external_number="WO-DETAIL-AUTH")
    db_session.add(work_order)
    db_session.commit()

    response = client.get(f"{LIST_URL}/{work_order.id}")

    assert response.status_code == 401


def test_get_work_order_detail_returns_header_and_lines(client, db_session, auth_headers) -> None:
    work_order = _make_work_order(external_number="WO-DETAIL-1", department="Кузовной цех")
    db_session.add(work_order)
    db_session.commit()
    db_session.add(
        WorkOrderLaborLine(
            work_order_id=work_order.id,
            operation_name="Окраска бампера",
            price=Decimal("1500.00"),
            amount=Decimal("1500.00"),
        )
    )
    db_session.add(
        WorkOrderPartLine(
            work_order_id=work_order.id,
            item_name="Бампер передний",
            quantity=Decimal("1.000"),
            price=Decimal("8000.00"),
            amount=Decimal("8000.00"),
        )
    )
    db_session.commit()

    response = client.get(f"{LIST_URL}/{work_order.id}", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["external_number"] == "WO-DETAIL-1"
    assert body["department"] == "Кузовной цех"
    assert len(body["labor"]) == 1
    assert body["labor"][0]["operation_name"] == "Окраска бампера"
    assert body["labor"][0]["amount"] == "1500.00"
    assert len(body["parts"]) == 1
    assert body["parts"][0]["item_name"] == "Бампер передний"
    assert body["parts"][0]["quantity"] == "1.000"
    # No status history for a work order that was never run through the
    # import pipeline (see test_import.py for the tracking itself).
    assert body["status_history"] == []


def test_get_work_order_detail_includes_status_history(client, db_session, auth_headers) -> None:
    import_payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-10T06:00:00",
        "batch_id": "detail-hist-1",
        "records": [
            {
                "number": "WO-DETAIL-HIST",
                "date": "2026-09-10T06:00:00",
                "customer": "Test Customer",
                "car": "VW TIGUAN",
                "amount": 1000,
                "status": "В работе",
            }
        ],
    }
    assert (
        client.post(
            "/api/v1/import/work-orders", json=import_payload, headers=auth_headers
        ).status_code
        == 200
    )

    import_payload["exported_at"] = "2026-09-12T06:00:00"
    import_payload["batch_id"] = "detail-hist-2"
    import_payload["records"][0]["status"] = "Ожидание запчастей"
    assert (
        client.post(
            "/api/v1/import/work-orders", json=import_payload, headers=auth_headers
        ).status_code
        == 200
    )

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "WO-DETAIL-HIST")
    ).scalar_one()

    response = client.get(f"{LIST_URL}/{work_order.id}", headers=auth_headers)

    assert response.status_code == 200
    history = response.json()["status_history"]
    assert len(history) == 2
    assert history[0]["status"] == "В работе"
    assert history[0]["last_seen_at"] == "2026-09-12T06:00:00Z"
    assert history[1]["status"] == "Ожидание запчастей"
    assert history[1]["last_seen_at"] is None


def test_get_work_order_detail_missing_returns_404(client, auth_headers) -> None:
    response = client.get(f"{LIST_URL}/00000000-0000-0000-0000-000000000000", headers=auth_headers)

    assert response.status_code == 404


class _FakeSettingsWithRevenueStatuses:
    """Minimal stand-in for Settings - only the one attribute the endpoints
    actually read off it, so tests don't have to fight Settings' required
    fields or its @lru_cache."""

    revenue_statuses_list = ["Закрыт"]


def test_monthly_summary_only_counts_configured_revenue_status(
    client, db_session, auth_headers, monkeypatch
) -> None:
    db_session.add(
        _make_work_order(
            external_number="WO-CLOSED",
            document_date=datetime(2026, 6, 5),
            closed_date=datetime(2026, 6, 5),
            amount=Decimal("100.00"),
            status="Закрыт",
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-OPEN",
            document_date=datetime(2026, 6, 10),
            closed_date=None,
            amount=Decimal("500.00"),
            status="Заявка",
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        "app.api.v1.endpoints.work_orders.get_settings",
        lambda: _FakeSettingsWithRevenueStatuses(),
    )

    response = client.get(SUMMARY_URL, headers=auth_headers)

    assert response.status_code == 200
    items = {item["month"]: item for item in response.json()["items"]}
    assert items["2026-06"]["work_order_count"] == 1
    assert items["2026-06"]["total_amount"] == "100.00"


def test_department_summary_only_counts_configured_revenue_status(
    client, db_session, auth_headers, monkeypatch
) -> None:
    db_session.add(
        _make_work_order(
            external_number="WO-CLOSED",
            department="Кузовной цех",
            amount=Decimal("300.00"),
            status="Закрыт",
            closed_date=datetime(2026, 6, 5),
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-OPEN",
            department="Кузовной цех",
            amount=Decimal("700.00"),
            status="Заявка",
            closed_date=None,
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        "app.api.v1.endpoints.work_orders.get_settings",
        lambda: _FakeSettingsWithRevenueStatuses(),
    )

    response = client.get(f"{LIST_URL}/summary/by-department", headers=auth_headers)

    assert response.status_code == 200
    items = {item["department"]: item for item in response.json()["items"]}
    assert items["Кузовной цех"]["total_amount"] == "300.00"
    assert items["Кузовной цех"]["work_order_count"] == 1


def test_status_summary_groups_and_sums_and_ignores_revenue_status_restriction(
    client, db_session, auth_headers, monkeypatch
) -> None:
    """Unlike monthly/by-department, this must NOT collapse to only the
    configured revenue status - it exists to show the full distribution."""
    db_session.add(
        _make_work_order(
            external_number="WO-CLOSED",
            status="Закрыт",
            amount=Decimal("300.00"),
            document_date=datetime(2026, 6, 5),
            closed_date=datetime(2026, 6, 5),
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-DECLINED-1",
            status="Отказ",
            amount=Decimal("500.00"),
            document_date=datetime(2026, 6, 6),
            closed_date=None,
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-DECLINED-2",
            status="Отказ",
            amount=Decimal("200.00"),
            document_date=datetime(2026, 6, 7),
            closed_date=None,
        )
    )
    db_session.add(_make_work_order(external_number="WO-NO-STATUS", status=None))
    db_session.commit()

    monkeypatch.setattr(
        "app.api.v1.endpoints.work_orders.get_settings",
        lambda: _FakeSettingsWithRevenueStatuses(),
    )

    response = client.get(f"{LIST_URL}/summary/by-status", headers=auth_headers)

    assert response.status_code == 200
    items = {item["status"]: item for item in response.json()["items"]}
    assert set(items) == {"Закрыт", "Отказ"}
    assert items["Закрыт"]["work_order_count"] == 1
    assert items["Отказ"]["work_order_count"] == 2
    assert items["Отказ"]["total_amount"] == "700.00"


def test_trend_summary_daily_granularity_for_a_one_month_span(
    client, db_session, auth_headers
) -> None:
    db_session.add(
        _make_work_order(
            external_number="WO-DAY-1",
            amount=Decimal("100.00"),
            closed_date=datetime(2026, 6, 5, 9, 0, 0),
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-DAY-2",
            amount=Decimal("50.00"),
            closed_date=datetime(2026, 6, 5, 15, 0, 0),
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-DAY-3",
            amount=Decimal("200.00"),
            closed_date=datetime(2026, 6, 6, 9, 0, 0),
        )
    )
    db_session.commit()

    response = client.get(
        f"{LIST_URL}/summary/trend",
        headers=auth_headers,
        params={"date_from": "2026-06-01T00:00:00", "date_to": "2026-07-01T00:00:00"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["granularity"] == "day"
    items = {item["period"]: item for item in body["items"]}
    assert items["2026-06-05"]["work_order_count"] == 2
    assert items["2026-06-05"]["total_amount"] == "150.00"
    assert items["2026-06-06"]["total_amount"] == "200.00"


def test_trend_summary_monthly_granularity_for_a_long_span(
    client, db_session, auth_headers
) -> None:
    db_session.add(
        _make_work_order(
            external_number="WO-JAN", amount=Decimal("100.00"), closed_date=datetime(2026, 1, 5)
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-JUN", amount=Decimal("200.00"), closed_date=datetime(2026, 6, 5)
        )
    )
    db_session.commit()

    response = client.get(
        f"{LIST_URL}/summary/trend",
        headers=auth_headers,
        params={"date_from": "2026-01-01T00:00:00", "date_to": "2026-07-01T00:00:00"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["granularity"] == "month"
    # Zero-filled: Jan and Jun have work orders, Feb-May don't but still
    # appear as 0-count buckets so the series stays gap-free.
    items = {item["period"]: item for item in body["items"]}
    assert set(items) == {
        "2026-01-01",
        "2026-02-01",
        "2026-03-01",
        "2026-04-01",
        "2026-05-01",
        "2026-06-01",
    }
    assert items["2026-01-01"]["total_amount"] == "100.00"
    assert items["2026-06-01"]["total_amount"] == "200.00"
    assert items["2026-03-01"]["work_order_count"] == 0
    assert items["2026-03-01"]["total_amount"] == "0"


def test_trend_summary_granularity_can_be_overridden(client, db_session, auth_headers) -> None:
    db_session.add(
        _make_work_order(
            external_number="WO-OVERRIDE",
            amount=Decimal("100.00"),
            closed_date=datetime(2026, 6, 5),
        )
    )
    db_session.commit()

    response = client.get(
        f"{LIST_URL}/summary/trend",
        headers=auth_headers,
        params={
            "date_from": "2026-06-01T00:00:00",
            "date_to": "2026-07-01T00:00:00",
            "granularity": "week",
        },
    )

    assert response.status_code == 200
    assert response.json()["granularity"] == "week"


def test_status_summary_filters_by_document_date(client, db_session, auth_headers) -> None:
    db_session.add(
        _make_work_order(
            external_number="WO-JUNE",
            status="Заявка",
            document_date=datetime(2026, 6, 10),
        )
    )
    db_session.add(
        _make_work_order(
            external_number="WO-JULY",
            status="Заявка",
            document_date=datetime(2026, 7, 10),
        )
    )
    db_session.commit()

    response = client.get(
        f"{LIST_URL}/summary/by-status",
        headers=auth_headers,
        params={"date_from": "2026-07-01T00:00:00", "date_to": "2026-08-01T00:00:00"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["work_order_count"] == 1
