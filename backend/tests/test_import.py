from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.models.import_batch import ImportBatch
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLaborLine, WorkOrderPartLine
from app.models.work_order_status_history import WorkOrderStatusHistory

IMPORT_URL = "/api/v1/import/work-orders"


def test_import_without_token_is_unauthorized(client, sample_import_payload) -> None:
    response = client.post(IMPORT_URL, json=sample_import_payload)

    assert response.status_code == 401


def test_import_with_wrong_token_is_unauthorized(client, sample_import_payload) -> None:
    response = client.post(
        IMPORT_URL,
        json=sample_import_payload,
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401


def test_valid_import_creates_work_order(
    client, db_session, auth_headers, sample_import_payload
) -> None:
    response = client.post(IMPORT_URL, json=sample_import_payload, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["received"] == 1
    assert body["inserted"] == 1
    assert body["updated"] == 0
    assert body["batch_id"] == sample_import_payload["batch_id"]

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PS00010196")
    ).scalar_one()
    assert work_order.source_system == "alpha-auto"
    assert work_order.customer_name == "Example Customer"
    assert work_order.amount == Decimal("18500")


def test_repeat_import_updates_record_instead_of_duplicating(
    client, db_session, auth_headers, sample_import_payload
) -> None:
    first = client.post(IMPORT_URL, json=sample_import_payload, headers=auth_headers)
    assert first.status_code == 200
    assert first.json()["inserted"] == 1
    assert first.json()["updated"] == 0

    changed_payload = dict(sample_import_payload)
    changed_payload["batch_id"] = sample_import_payload["batch_id"] + "-retry"
    changed_payload["records"] = [dict(sample_import_payload["records"][0])]
    changed_payload["records"][0]["amount"] = 19999

    second = client.post(IMPORT_URL, json=changed_payload, headers=auth_headers)
    assert second.status_code == 200
    assert second.json()["inserted"] == 0
    assert second.json()["updated"] == 1

    rows = (
        db_session.execute(select(WorkOrder).where(WorkOrder.external_number == "PS00010196"))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].amount == Decimal("19999")


def test_import_batch_is_recorded(client, db_session, auth_headers, sample_import_payload) -> None:
    response = client.post(IMPORT_URL, json=sample_import_payload, headers=auth_headers)
    assert response.status_code == 200

    batch = db_session.execute(
        select(ImportBatch).where(ImportBatch.batch_id == sample_import_payload["batch_id"])
    ).scalar_one()

    assert batch.source == "alpha-auto"
    assert batch.entity == "work_orders"
    assert batch.branch == "kahovka"
    assert batch.status == "success"
    assert batch.records_received == 1
    assert batch.records_inserted == 1
    assert batch.records_updated == 0
    assert batch.error_message is None


def test_import_stores_status_department_labor_and_parts(client, db_session, auth_headers) -> None:
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-13T10:00:00",
        "batch_id": "lines-test-1",
        "records": [
            {
                "number": "LINES-0001",
                "date": "2026-09-12T18:38:09",
                "customer": "Test Customer",
                "car": "VW TIGUAN",
                "amount": 5500,
                "status": "В работе",
                "department": "Кузовной цех",
                "labor": [{"operation": "Снятие бампера", "price": 500, "amount": 500}],
                "parts": [
                    {"item": "Бампер передний", "quantity": 1, "price": 5000, "amount": 5000}
                ],
            }
        ],
    }

    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)
    assert response.status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "LINES-0001")
    ).scalar_one()
    assert work_order.status == "В работе"
    assert work_order.department == "Кузовной цех"

    labor_lines = (
        db_session.execute(
            select(WorkOrderLaborLine).where(WorkOrderLaborLine.work_order_id == work_order.id)
        )
        .scalars()
        .all()
    )
    assert len(labor_lines) == 1
    assert labor_lines[0].operation_name == "Снятие бампера"
    assert labor_lines[0].amount == Decimal("500.00")

    part_lines = (
        db_session.execute(
            select(WorkOrderPartLine).where(WorkOrderPartLine.work_order_id == work_order.id)
        )
        .scalars()
        .all()
    )
    assert len(part_lines) == 1
    assert part_lines[0].item_name == "Бампер передний"
    assert part_lines[0].quantity == Decimal("1.000")

    # Re-import with a different set of lines - old lines must be replaced,
    # not accumulated alongside the new ones.
    payload["records"][0]["labor"] = [
        {"operation": "Снятие бампера", "price": 500, "amount": 500},
        {"operation": "Покраска бампера", "price": 1500, "amount": 1500},
    ]
    payload["records"][0]["parts"] = []
    payload["batch_id"] = "lines-test-2"

    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["updated"] == 1

    labor_lines_after = (
        db_session.execute(
            select(WorkOrderLaborLine).where(WorkOrderLaborLine.work_order_id == work_order.id)
        )
        .scalars()
        .all()
    )
    assert len(labor_lines_after) == 2

    part_lines_after = (
        db_session.execute(
            select(WorkOrderPartLine).where(WorkOrderPartLine.work_order_id == work_order.id)
        )
        .scalars()
        .all()
    )
    assert len(part_lines_after) == 0


def test_import_stores_the_four_document_dates(client, db_session, auth_headers) -> None:
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-13T10:00:00",
        "batch_id": "dates-test-1",
        "records": [
            {
                "number": "DATES-0001",
                "date": "2026-06-15T10:00:00",
                "customer": "Test Customer",
                "car": "VW TIGUAN",
                "amount": 1000,
                "created_date": "2026-06-15T09:00:00",
                "start_date": "2026-06-16T08:00:00",
                "end_date": "2026-09-09T17:00:00",
                "closed_date": "2026-09-10T12:00:00",
            }
        ],
    }

    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)
    assert response.status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "DATES-0001")
    ).scalar_one()
    assert work_order.created_date == datetime(2026, 6, 15, 9, 0, 0, tzinfo=UTC)
    assert work_order.start_date == datetime(2026, 6, 16, 8, 0, 0, tzinfo=UTC)
    assert work_order.end_date == datetime(2026, 9, 9, 17, 0, 0, tzinfo=UTC)
    assert work_order.closed_date == datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)


def _import_status(client, auth_headers, status, exported_at, batch_id) -> None:
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": exported_at,
        "batch_id": batch_id,
        "records": [
            {
                "number": "HIST-0001",
                "date": "2026-09-10T06:00:00",
                "customer": "Test Customer",
                "car": "VW TIGUAN",
                "amount": 1000,
                "status": status,
            }
        ],
    }
    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)
    assert response.status_code == 200


def _status_history(db_session, work_order_id) -> list[WorkOrderStatusHistory]:
    return list(
        db_session.execute(
            select(WorkOrderStatusHistory)
            .where(WorkOrderStatusHistory.work_order_id == work_order_id)
            .order_by(WorkOrderStatusHistory.first_seen_at)
        ).scalars()
    )


def test_status_history_opens_a_segment_on_first_import(client, db_session, auth_headers) -> None:
    _import_status(client, auth_headers, "В работе", "2026-09-10T06:00:00", "hist-1")

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "HIST-0001")
    ).scalar_one()
    rows = _status_history(db_session, work_order.id)

    assert len(rows) == 1
    assert rows[0].status == "В работе"
    assert rows[0].first_seen_at == datetime(2026, 9, 10, 6, 0, 0, tzinfo=UTC)
    assert rows[0].last_seen_at is None


def test_status_history_unchanged_status_does_not_add_a_row(
    client, db_session, auth_headers
) -> None:
    _import_status(client, auth_headers, "В работе", "2026-09-10T06:00:00", "hist-1")
    _import_status(client, auth_headers, "В работе", "2026-09-11T06:00:00", "hist-2")

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "HIST-0001")
    ).scalar_one()
    rows = _status_history(db_session, work_order.id)

    assert len(rows) == 1
    assert rows[0].last_seen_at is None


def test_status_history_transition_closes_old_row_and_opens_new_one(
    client, db_session, auth_headers
) -> None:
    """The exact scenario from the spec: В работе (10.09) -> unchanged
    (11.09, no-op) -> Ожидание запчастей (12.09) closes В работе and opens
    a new open segment."""
    _import_status(client, auth_headers, "В работе", "2026-09-10T06:00:00", "hist-1")
    _import_status(client, auth_headers, "В работе", "2026-09-11T06:00:00", "hist-2")
    _import_status(client, auth_headers, "Ожидание запчастей", "2026-09-12T06:00:00", "hist-3")

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "HIST-0001")
    ).scalar_one()
    rows = _status_history(db_session, work_order.id)

    assert len(rows) == 2
    assert rows[0].status == "В работе"
    assert rows[0].first_seen_at == datetime(2026, 9, 10, 6, 0, 0, tzinfo=UTC)
    assert rows[0].last_seen_at == datetime(2026, 9, 12, 6, 0, 0, tzinfo=UTC)
    assert rows[1].status == "Ожидание запчастей"
    assert rows[1].first_seen_at == datetime(2026, 9, 12, 6, 0, 0, tzinfo=UTC)
    assert rows[1].last_seen_at is None


def test_status_history_ignores_a_missing_status(client, db_session, auth_headers) -> None:
    """No status on the incoming record - nothing to track, and the
    previously-open segment (if any) stays open rather than being closed
    out by a non-status."""
    _import_status(client, auth_headers, "В работе", "2026-09-10T06:00:00", "hist-1")
    _import_status(client, auth_headers, None, "2026-09-11T06:00:00", "hist-2")

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "HIST-0001")
    ).scalar_one()
    rows = _status_history(db_session, work_order.id)

    assert len(rows) == 1
    assert rows[0].status == "В работе"
    assert rows[0].last_seen_at is None


def test_import_accepts_missing_document_dates_as_null(
    client, db_session, auth_headers, sample_import_payload
) -> None:
    """An open work order won't have a closed_date (or maybe start/end)
    yet - the field must be optional, not required."""
    response = client.post(IMPORT_URL, json=sample_import_payload, headers=auth_headers)
    assert response.status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PS00010196")
    ).scalar_one()
    assert work_order.created_date is None
    assert work_order.start_date is None
    assert work_order.end_date is None
    assert work_order.closed_date is None
