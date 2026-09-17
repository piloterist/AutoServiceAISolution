from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.models.import_batch import ImportBatch
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLaborLine, WorkOrderPartLine
from app.models.work_order_payment_event import WorkOrderPaymentEvent
from app.models.work_order_payment_history import WorkOrderPaymentHistory
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


def test_import_stores_repair_type(client, db_session, auth_headers) -> None:
    """ЗаказНаряд.ВидРемонта - captured starting now (see
    schemas/import_work_order.py) but not yet exposed on any read endpoint;
    this only proves it's actually reaching the work_orders row."""
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-16T10:00:00",
        "batch_id": "repair-type-test-1",
        "records": [
            {
                "number": "REPAIR-TYPE-0001",
                "date": "2026-09-16T09:00:00",
                "customer": "Test Customer",
                "car": "VW TIGUAN",
                "amount": 3000,
                "repair_type": "Аварийный ремонт",
            }
        ],
    }

    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)
    assert response.status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "REPAIR-TYPE-0001")
    ).scalar_one()
    assert work_order.repair_type == "Аварийный ремонт"


def test_import_accepts_missing_repair_type_as_null(
    client, db_session, auth_headers, sample_import_payload
) -> None:
    response = client.post(IMPORT_URL, json=sample_import_payload, headers=auth_headers)
    assert response.status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PS00010196")
    ).scalar_one()
    assert work_order.repair_type is None


def test_import_stores_organization_and_payer(client, db_session, auth_headers) -> None:
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-17T10:00:00",
        "batch_id": "org-payer-test-1",
        "records": [
            {
                "number": "ORG-PAYER-0001",
                "date": "2026-09-17T09:00:00",
                "customer": "Test Customer",
                "car": "VW TIGUAN",
                "amount": 3000,
                "organization": "ООО Пан Моторс",
                "payer": "СПАО Ингосстрах",
            }
        ],
    }

    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)
    assert response.status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "ORG-PAYER-0001")
    ).scalar_one()
    assert work_order.organization == "ООО Пан Моторс"
    assert work_order.payer_name == "СПАО Ингосстрах"


def test_import_stores_payment_fields(client, db_session, auth_headers) -> None:
    """deal_amount/debt_amount/paid_amount/payment_percent - computed by the
    1C export itself (5S AUTO's own ВзаиморасчетыКомпании logic), just
    stored as sent."""
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-16T10:00:00",
        "batch_id": "payment-test-1",
        "records": [
            {
                "number": "PAYMENT-0001",
                "date": "2026-09-16T09:00:00",
                "customer": "Test Customer",
                "car": "VW TIGUAN",
                "amount": 231710.80,
                "deal_amount": 231710.80,
                "debt_amount": 181710.80,
                "paid_amount": 50000.00,
                "payment_percent": 21.58,
            }
        ],
    }

    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)
    assert response.status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PAYMENT-0001")
    ).scalar_one()
    assert work_order.deal_amount == Decimal("231710.80")
    assert work_order.debt_amount == Decimal("181710.80")
    assert work_order.paid_amount == Decimal("50000.00")
    assert work_order.payment_percent == Decimal("21.58")


def test_import_accepts_missing_payment_fields_as_null(
    client, db_session, auth_headers, sample_import_payload
) -> None:
    """Backward compatibility - an older export with no payment fields at
    all must keep importing exactly as before."""
    response = client.post(IMPORT_URL, json=sample_import_payload, headers=auth_headers)
    assert response.status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PS00010196")
    ).scalar_one()
    assert work_order.deal_amount is None
    assert work_order.debt_amount is None
    assert work_order.paid_amount is None
    assert work_order.payment_percent is None


def test_import_allows_negative_and_over_100_payment_percent(
    client, db_session, auth_headers
) -> None:
    """5S AUTO's own figure isn't clamped to 0..100 (overpayment, unusual
    settlement states) - neither is ours."""
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-16T10:00:00",
        "batch_id": "payment-overpaid-1",
        "records": [
            {
                "number": "PAYMENT-OVERPAID",
                "date": "2026-09-16T09:00:00",
                "customer": "Test Customer",
                "car": "VW TIGUAN",
                "amount": 10000,
                "deal_amount": 10000,
                "debt_amount": -2000,
                "paid_amount": 12000,
                "payment_percent": 120.00,
            }
        ],
    }

    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)
    assert response.status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PAYMENT-OVERPAID")
    ).scalar_one()
    assert work_order.debt_amount == Decimal("-2000.00")
    assert work_order.payment_percent == Decimal("120.00")


def _payment_events(db_session, work_order_id) -> list[WorkOrderPaymentEvent]:
    return list(
        db_session.execute(
            select(WorkOrderPaymentEvent)
            .where(WorkOrderPaymentEvent.work_order_id == work_order_id)
            .order_by(WorkOrderPaymentEvent.paid_at)
        ).scalars()
    )


def test_import_stores_payment_events(client, db_session, auth_headers) -> None:
    """payment_events - the real dated ledger from
    РегистрНакопления.ВзаиморасчетыКомпании (see 1c/TestExportOrders.bsl's
    payments batch query), distinct from the deal/debt/paid snapshot."""
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-16T10:00:00",
        "batch_id": "payment-events-test-1",
        "records": [
            {
                "number": "PAYMENT-EVT-0001",
                "date": "2026-09-16T09:00:00",
                "customer": "Test Customer",
                "car": "VW TIGUAN",
                "amount": 1139200,
                "payment_events": [
                    {
                        "paid_at": "2026-05-20T14:05:21",
                        "amount": 500000.00,
                        "source_document_id": "a1b2c3d4-0000-0000-0000-000000000001",
                        "source_document_type": "Чек на оплату",
                        "source_document_number": "ЭП00000251",
                        "line_number": 1,
                    }
                ],
            }
        ],
    }

    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)
    assert response.status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PAYMENT-EVT-0001")
    ).scalar_one()
    events = _payment_events(db_session, work_order.id)
    assert len(events) == 1
    assert events[0].amount == Decimal("500000.00")
    assert events[0].paid_at == datetime(2026, 5, 20, 14, 5, 21, tzinfo=UTC)
    assert events[0].source_document_type == "Чек на оплату"


def test_import_accepts_missing_payment_events_as_empty(
    client, db_session, auth_headers, sample_import_payload
) -> None:
    """Backward compatibility - an older export with no payment_events at
    all must keep importing exactly as before, with no rows created."""
    response = client.post(IMPORT_URL, json=sample_import_payload, headers=auth_headers)
    assert response.status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PS00010196")
    ).scalar_one()
    assert _payment_events(db_session, work_order.id) == []


def test_import_payment_events_is_idempotent_on_reimport(client, db_session, auth_headers) -> None:
    """A full historical re-export resends every payment for every work
    order every time - re-importing the same (work_order, document, line)
    must not create a duplicate row."""
    record = {
        "number": "PAYMENT-EVT-DUP",
        "date": "2026-09-16T09:00:00",
        "customer": "Test Customer",
        "car": "VW TIGUAN",
        "amount": 500000,
        "payment_events": [
            {
                "paid_at": "2026-05-20T14:05:21",
                "amount": 500000.00,
                "source_document_id": "a1b2c3d4-0000-0000-0000-000000000002",
                "line_number": 1,
            }
        ],
    }
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-16T10:00:00",
        "batch_id": "payment-events-dup-1",
        "records": [record],
    }

    assert client.post(IMPORT_URL, json=payload, headers=auth_headers).status_code == 200
    payload["batch_id"] = "payment-events-dup-2"
    assert client.post(IMPORT_URL, json=payload, headers=auth_headers).status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PAYMENT-EVT-DUP")
    ).scalar_one()
    assert len(_payment_events(db_session, work_order.id)) == 1


def _payment_history(db_session, work_order_id) -> list[WorkOrderPaymentHistory]:
    return list(
        db_session.execute(
            select(WorkOrderPaymentHistory)
            .where(WorkOrderPaymentHistory.work_order_id == work_order_id)
            .order_by(WorkOrderPaymentHistory.observed_at)
        ).scalars()
    )


def _import_payment(client, auth_headers, batch_id, **payment_fields) -> None:
    record = {
        "number": "PAYMENT-HIST-0001",
        "date": "2026-09-16T09:00:00",
        "customer": "Test Customer",
        "car": "VW TIGUAN",
        "amount": 10000,
        **payment_fields,
    }
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-16T10:00:00",
        "batch_id": batch_id,
        "records": [record],
    }
    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)
    assert response.status_code == 200


def test_payment_history_creates_a_snapshot_on_first_import(
    client, db_session, auth_headers
) -> None:
    _import_payment(
        client,
        auth_headers,
        "payment-hist-1",
        deal_amount=10000,
        debt_amount=10000,
        paid_amount=0,
        payment_percent=0,
    )

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PAYMENT-HIST-0001")
    ).scalar_one()
    rows = _payment_history(db_session, work_order.id)

    assert len(rows) == 1
    assert rows[0].deal_amount == Decimal("10000.00")
    assert rows[0].debt_amount == Decimal("10000.00")
    assert rows[0].paid_amount == Decimal("0.00")
    assert rows[0].payment_percent == Decimal("0.00")


def test_payment_history_unchanged_values_do_not_add_a_row(
    client, db_session, auth_headers
) -> None:
    _import_payment(
        client,
        auth_headers,
        "payment-hist-1",
        deal_amount=10000,
        debt_amount=10000,
        paid_amount=0,
        payment_percent=0,
    )
    _import_payment(
        client,
        auth_headers,
        "payment-hist-2",
        deal_amount=10000,
        debt_amount=10000,
        paid_amount=0,
        payment_percent=0,
    )

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PAYMENT-HIST-0001")
    ).scalar_one()
    rows = _payment_history(db_session, work_order.id)

    assert len(rows) == 1


def test_payment_history_adds_a_row_when_debt_changes(client, db_session, auth_headers) -> None:
    _import_payment(
        client,
        auth_headers,
        "payment-hist-1",
        deal_amount=10000,
        debt_amount=10000,
        paid_amount=0,
        payment_percent=0,
    )
    _import_payment(
        client,
        auth_headers,
        "payment-hist-2",
        deal_amount=10000,
        debt_amount=4000,
        paid_amount=6000,
        payment_percent=60,
    )

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PAYMENT-HIST-0001")
    ).scalar_one()
    rows = _payment_history(db_session, work_order.id)

    assert len(rows) == 2
    assert rows[0].debt_amount == Decimal("10000.00")
    assert rows[1].debt_amount == Decimal("4000.00")
    assert rows[1].paid_amount == Decimal("6000.00")
    assert rows[1].payment_percent == Decimal("60.00")
    assert rows[1].observed_at > rows[0].observed_at


def test_payment_history_ignores_a_reimport_with_no_payment_data(
    client, db_session, auth_headers
) -> None:
    """A later re-import that doesn't send payment fields at all (e.g. an
    older-style batch) must not be mistaken for "payment data cleared" -
    the existing snapshot just stays as the latest one."""
    _import_payment(
        client,
        auth_headers,
        "payment-hist-1",
        deal_amount=10000,
        debt_amount=10000,
        paid_amount=0,
        payment_percent=0,
    )
    _import_payment(client, auth_headers, "payment-hist-2")

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PAYMENT-HIST-0001")
    ).scalar_one()
    rows = _payment_history(db_session, work_order.id)

    assert len(rows) == 1


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
    before = datetime.now(UTC)
    _import_status(client, auth_headers, "В работе", "2026-09-10T06:00:00", "hist-1")
    after = datetime.now(UTC)

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "HIST-0001")
    ).scalar_one()
    rows = _status_history(db_session, work_order.id)

    assert len(rows) == 1
    assert rows[0].status == "В работе"
    # Timestamped with the server's own clock at processing time, not the
    # request's `exported_at` - 1C sends that as a naive local (MSK)
    # timestamp with no timezone info, so storing it as-is would mislabel
    # it as UTC.
    assert before <= rows[0].first_seen_at <= after
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
    before_transition = datetime.now(UTC)
    _import_status(client, auth_headers, "Ожидание запчастей", "2026-09-12T06:00:00", "hist-3")
    after_transition = datetime.now(UTC)

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "HIST-0001")
    ).scalar_one()
    rows = _status_history(db_session, work_order.id)

    assert len(rows) == 2
    assert rows[0].status == "В работе"
    assert rows[0].last_seen_at is not None
    assert before_transition <= rows[0].last_seen_at <= after_transition
    assert rows[1].status == "Ожидание запчастей"
    # The close of the old segment and the open of the new one share the
    # same "observed at" timestamp - one batch, one processing moment.
    assert rows[1].first_seen_at == rows[0].last_seen_at
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
