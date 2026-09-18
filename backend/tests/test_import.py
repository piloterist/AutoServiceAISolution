import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.models.import_batch import ImportBatch
from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLaborLine, WorkOrderPartLine
from app.models.work_order_payment_event import WorkOrderPaymentEvent
from app.models.work_order_payment_history import WorkOrderPaymentHistory
from app.models.work_order_status_history import WorkOrderStatusHistory
from app.services import import_service

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
    # 1C sends 14:05:21 as naive MSK (UTC+3), not UTC - see
    # import_service._naive_msk_to_utc.
    assert events[0].paid_at == datetime(2026, 5, 20, 11, 5, 21, tzinfo=UTC)
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


def test_import_payment_events_reimport_corrects_a_previously_wrong_value(
    client, db_session, auth_headers
) -> None:
    """A re-export must be able to fix an already-stored row, not just
    silently skip it as a duplicate - this is exactly what backfills
    existing rows onto a corrected paid_at (e.g. the MSK->UTC timezone
    fix - see _naive_msk_to_utc) the next time each work order is
    re-exported, without a separate one-off data migration."""
    record = {
        "number": "PAYMENT-EVT-FIX",
        "date": "2026-09-16T09:00:00",
        "customer": "Test Customer",
        "car": "VW TIGUAN",
        "amount": 500000,
        "payment_events": [
            {
                "paid_at": "2026-05-20T14:05:21",
                "amount": 500000.00,
                "source_document_id": "a1b2c3d4-0000-0000-0000-000000000003",
                "line_number": 1,
            }
        ],
    }
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-16T10:00:00",
        "batch_id": "payment-events-fix-1",
        "records": [record],
    }
    assert client.post(IMPORT_URL, json=payload, headers=auth_headers).status_code == 200

    # Same document/line, but a corrected amount and paid_at this time.
    record["payment_events"][0]["amount"] = 450000.00
    record["payment_events"][0]["paid_at"] = "2026-05-20T09:00:00"
    payload["batch_id"] = "payment-events-fix-2"
    assert client.post(IMPORT_URL, json=payload, headers=auth_headers).status_code == 200

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "PAYMENT-EVT-FIX")
    ).scalar_one()
    events = _payment_events(db_session, work_order.id)
    assert len(events) == 1
    assert events[0].amount == Decimal("450000.00")
    assert events[0].paid_at == datetime(2026, 5, 20, 6, 0, 0, tzinfo=UTC)


def test_naive_msk_to_utc_converts_assuming_moscow_time() -> None:
    naive = datetime(2026, 9, 16, 18, 51, 30)
    assert import_service._naive_msk_to_utc(naive) == datetime(2026, 9, 16, 15, 51, 30, tzinfo=UTC)


def test_naive_msk_to_utc_passes_through_an_already_aware_value() -> None:
    aware = datetime(2026, 9, 16, 18, 51, 30, tzinfo=UTC)
    assert import_service._naive_msk_to_utc(aware) == aware


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


def _version(
    version_number,
    changed_at,
    status,
    author="Ледяев Дмитрий Юрьевич",
    status_uuid="57da537c-ad25-11e9-80d5-de6a32a93df3",
) -> dict:
    """One РегистрСведений.пп_ВерсииОбъектов entry, as the 1C export sends
    it (see ImportStatusHistoryRecord)."""
    return {
        "version_number": version_number,
        "changed_at": changed_at,
        "author": author,
        "status": status,
        "status_uuid": status_uuid,
    }


def _import_with_status_history(
    client, auth_headers, batch_id, status_history, number="HIST-0001", status=None
) -> None:
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-18T06:00:00",
        "batch_id": batch_id,
        "records": [
            {
                "number": number,
                "date": "2026-09-10T06:00:00",
                "customer": "Test Customer",
                "car": "VW TIGUAN",
                "amount": 1000,
                "status": status,
                "status_history": status_history,
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
            .order_by(WorkOrderStatusHistory.version_number)
        ).scalars()
    )


def _get_work_order(db_session, number: str) -> WorkOrder:
    return db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == number)
    ).scalar_one()


def test_status_history_first_import_creates_events(client, db_session, auth_headers) -> None:
    """Scenario 1 (first import) - every version with a resolvable status
    becomes a row, since there's nothing earlier to compare against."""
    _import_with_status_history(
        client,
        auth_headers,
        "hist-1",
        [
            _version(1, "2026-09-16T15:17:03", "В работе"),
            _version(2, "2026-09-16T15:17:13", "Выполнен"),
        ],
    )

    work_order = _get_work_order(db_session, "HIST-0001")
    rows = _status_history(db_session, work_order.id)

    assert len(rows) == 2
    assert rows[0].version_number == 1
    assert rows[0].status == "В работе"
    assert rows[1].version_number == 2
    assert rows[1].status == "Выполнен"


def test_status_history_reimport_of_identical_payload_creates_no_duplicates(
    client, db_session, auth_headers
) -> None:
    """Scenario 2 - a full re-export resends the same available version
    history every time; re-importing it must not duplicate rows."""
    versions = [
        _version(1, "2026-09-16T15:17:03", "В работе"),
        _version(2, "2026-09-16T15:17:13", "Выполнен"),
    ]
    _import_with_status_history(client, auth_headers, "hist-1", versions)
    _import_with_status_history(client, auth_headers, "hist-2", versions)

    work_order = _get_work_order(db_session, "HIST-0001")
    rows = _status_history(db_session, work_order.id)

    assert len(rows) == 2


def test_status_history_collapses_consecutive_same_status_versions(
    client, db_session, auth_headers
) -> None:
    """Scenario 5, the exact sequence from the spec: v1/v2/v3 all "В
    работе" collapse to one row, only the transitions to "Выполнен" and
    "Закрыт" get their own row."""
    _import_with_status_history(
        client,
        auth_headers,
        "hist-1",
        [
            _version(1, "2026-09-16T15:17:03", "В работе"),
            _version(2, "2026-09-16T16:00:00", "В работе"),
            _version(3, "2026-09-16T17:00:00", "В работе"),
            _version(4, "2026-09-16T18:00:00", "Выполнен"),
            _version(5, "2026-09-17T09:00:00", "Выполнен"),
            _version(6, "2026-09-17T12:59:06", "Закрыт"),
        ],
    )

    work_order = _get_work_order(db_session, "HIST-0001")
    rows = _status_history(db_session, work_order.id)

    assert [(row.version_number, row.status) for row in rows] == [
        (1, "В работе"),
        (4, "Выполнен"),
        (6, "Закрыт"),
    ]


def test_status_history_new_version_with_new_status_adds_an_event(
    client, db_session, auth_headers
) -> None:
    """Scenario 3."""
    _import_with_status_history(
        client, auth_headers, "hist-1", [_version(1, "2026-09-16T15:17:03", "В работе")]
    )
    _import_with_status_history(
        client,
        auth_headers,
        "hist-2",
        [
            _version(1, "2026-09-16T15:17:03", "В работе"),
            _version(2, "2026-09-17T12:59:06", "Закрыт"),
        ],
    )

    work_order = _get_work_order(db_session, "HIST-0001")
    rows = _status_history(db_session, work_order.id)

    assert [(row.version_number, row.status) for row in rows] == [
        (1, "В работе"),
        (2, "Закрыт"),
    ]


def test_status_history_new_version_with_same_status_adds_no_event(
    client, db_session, auth_headers
) -> None:
    """Scenario 4."""
    _import_with_status_history(
        client, auth_headers, "hist-1", [_version(1, "2026-09-16T15:17:03", "В работе")]
    )
    _import_with_status_history(
        client,
        auth_headers,
        "hist-2",
        [
            _version(1, "2026-09-16T15:17:03", "В работе"),
            _version(2, "2026-09-16T16:00:00", "В работе"),
        ],
    )

    work_order = _get_work_order(db_session, "HIST-0001")
    rows = _status_history(db_session, work_order.id)

    assert len(rows) == 1
    assert rows[0].version_number == 1


def test_status_history_multiple_new_versions_between_imports(
    client, db_session, auth_headers
) -> None:
    """Scenario 6 - several new versions arrive at once, some real
    transitions among them, some not."""
    _import_with_status_history(
        client,
        auth_headers,
        "hist-1",
        [
            _version(1, "2026-09-16T15:17:03", "В работе"),
            _version(2, "2026-09-16T15:17:13", "Выполнен"),
        ],
    )
    _import_with_status_history(
        client,
        auth_headers,
        "hist-2",
        [
            _version(1, "2026-09-16T15:17:03", "В работе"),
            _version(2, "2026-09-16T15:17:13", "Выполнен"),
            _version(3, "2026-09-16T20:00:00", "Выполнен"),  # no-op
            _version(4, "2026-09-17T08:00:00", "Согласование"),  # real change
            _version(5, "2026-09-17T12:59:06", "Закрыт"),  # real change
        ],
    )

    work_order = _get_work_order(db_session, "HIST-0001")
    rows = _status_history(db_session, work_order.id)

    assert [(row.version_number, row.status) for row in rows] == [
        (1, "В работе"),
        (2, "Выполнен"),
        (4, "Согласование"),
        (5, "Закрыт"),
    ]


def test_status_history_handles_many_versions(client, db_session, auth_headers) -> None:
    """Scenario 8 - an old work order with a long version history (mostly
    unrelated edits, a handful of real status changes)."""
    versions = []
    for i in range(1, 21):
        status = "В работе" if i < 15 else "Закрыт"
        versions.append(_version(i, f"2026-01-{i:02d}T10:00:00", status))
    _import_with_status_history(client, auth_headers, "hist-1", versions)

    work_order = _get_work_order(db_session, "HIST-0001")
    rows = _status_history(db_session, work_order.id)

    assert [(row.version_number, row.status) for row in rows] == [
        (1, "В работе"),
        (15, "Закрыт"),
    ]


def test_status_history_empty_when_no_versions_sent(client, db_session, auth_headers) -> None:
    """Scenario 9 - a work order with nothing in
    пп_ВерсииОбъектов (or an older export that doesn't send this field at
    all) must not error, just have no history rows."""
    _import_with_status_history(client, auth_headers, "hist-1", [])

    work_order = _get_work_order(db_session, "HIST-0001")
    assert _status_history(db_session, work_order.id) == []


def test_status_history_skips_a_version_without_a_resolvable_status(
    client, db_session, auth_headers
) -> None:
    """Scenarios 10-12: a version with no status (1C couldn't resolve
    Состояние/its UUID, or the BSL export skipped a broken version and
    just sent status=None) is skipped entirely - it doesn't create a row,
    doesn't reset the "previous status" comparison, and doesn't stop the
    other versions in the same batch from being processed."""
    _import_with_status_history(
        client,
        auth_headers,
        "hist-1",
        [
            _version(1, "2026-09-16T15:17:03", "В работе"),
            _version(2, "2026-09-16T16:00:00", None, status_uuid=None),  # unresolvable
            _version(3, "2026-09-16T17:00:00", "В работе"),  # same as v1 - still a no-op
            _version(4, "2026-09-17T12:59:06", "Закрыт"),
        ],
    )

    work_order = _get_work_order(db_session, "HIST-0001")
    rows = _status_history(db_session, work_order.id)

    assert [(row.version_number, row.status) for row in rows] == [
        (1, "В работе"),
        (4, "Закрыт"),
    ]


def test_status_history_importing_one_work_order_does_not_affect_another(
    client, db_session, auth_headers
) -> None:
    """Scenario 13."""
    _import_with_status_history(
        client,
        auth_headers,
        "hist-1",
        [_version(1, "2026-09-16T15:17:03", "В работе")],
        number="HIST-A",
    )
    _import_with_status_history(
        client,
        auth_headers,
        "hist-2",
        [_version(1, "2026-09-16T15:17:03", "Закрыт")],
        number="HIST-B",
    )

    work_order_a = _get_work_order(db_session, "HIST-A")
    work_order_b = _get_work_order(db_session, "HIST-B")

    assert [row.status for row in _status_history(db_session, work_order_a.id)] == ["В работе"]
    assert [row.status for row in _status_history(db_session, work_order_b.id)] == ["Закрыт"]


def test_status_history_partial_reimport_keeps_earlier_history(
    client, db_session, auth_headers
) -> None:
    """Scenario 14 - a later import that only knows about a newer slice of
    the version history (e.g. a scoped/partial export) must not delete the
    rows an earlier, fuller import already created; this is an incremental
    upsert, not delete-then-insert (see _record_status_history)."""
    _import_with_status_history(
        client,
        auth_headers,
        "hist-1",
        [
            _version(1, "2026-09-16T15:17:03", "В работе"),
            _version(2, "2026-09-16T15:17:13", "Выполнен"),
        ],
    )
    _import_with_status_history(
        client, auth_headers, "hist-2", [_version(3, "2026-09-17T12:59:06", "Закрыт")]
    )

    work_order = _get_work_order(db_session, "HIST-0001")
    rows = _status_history(db_session, work_order.id)

    assert [(row.version_number, row.status) for row in rows] == [
        (1, "В работе"),
        (2, "Выполнен"),
        (3, "Закрыт"),
    ]


def test_status_history_reconciles_a_stale_row_when_a_gap_is_filled(
    client, db_session, auth_headers
) -> None:
    """A version that looked like a real transition when an earlier import
    had a gap in its available history (version 2 missing, say a
    transient read error) must be reconciled away once a later import
    fills that gap and shows it was actually a no-op (same status as the
    version now known to precede it) - not left behind as a stale row."""
    _import_with_status_history(
        client,
        auth_headers,
        "hist-1",
        [
            _version(1, "2026-09-16T15:17:03", "В работе"),
            _version(3, "2026-09-17T09:00:00", "Выполнен"),
        ],
    )

    work_order = _get_work_order(db_session, "HIST-0001")
    assert [
        (row.version_number, row.status) for row in _status_history(db_session, work_order.id)
    ] == [
        (1, "В работе"),
        (3, "Выполнен"),
    ]

    _import_with_status_history(
        client,
        auth_headers,
        "hist-2",
        [
            _version(1, "2026-09-16T15:17:03", "В работе"),
            _version(2, "2026-09-16T20:00:00", "Выполнен"),
            _version(3, "2026-09-17T09:00:00", "Выполнен"),
        ],
    )

    rows = _status_history(db_session, work_order.id)
    assert [(row.version_number, row.status) for row in rows] == [
        (1, "В работе"),
        (2, "Выполнен"),
    ]


def test_status_history_changed_at_comes_from_version_date_not_import_time(
    client, db_session, auth_headers
) -> None:
    """Scenarios 15-16 - changed_at is 1C's own ДатаВерсии, verbatim,
    never the request's exported_at or this backend's own clock."""
    before_import = datetime.now(UTC)
    _import_with_status_history(
        client, auth_headers, "hist-1", [_version(1, "2026-09-16T15:17:03", "В работе")]
    )
    after_import = datetime.now(UTC)

    work_order = _get_work_order(db_session, "HIST-0001")
    rows = _status_history(db_session, work_order.id)

    # 1C sends 15:17:03 as naive MSK (UTC+3), not UTC - see
    # import_service._naive_msk_to_utc.
    assert rows[0].changed_at == datetime(2026, 9, 16, 12, 17, 3, tzinfo=UTC)
    assert rows[0].changed_at < before_import
    assert rows[0].changed_at < after_import


def test_status_history_stores_author(client, db_session, auth_headers) -> None:
    """Scenario 17."""
    _import_with_status_history(
        client,
        auth_headers,
        "hist-1",
        [_version(1, "2026-09-16T15:17:03", "В работе", author="Ледяев Дмитрий Юрьевич")],
    )

    work_order = _get_work_order(db_session, "HIST-0001")
    rows = _status_history(db_session, work_order.id)

    assert rows[0].author == "Ледяев Дмитрий Юрьевич"


def test_status_history_old_diff_based_mechanism_no_longer_fires(
    client, db_session, auth_headers
) -> None:
    """Scenario 18 - the work order's plain `status` field changing
    between imports (the old mechanism's trigger) must NOT create a
    status_history row on its own when status_history isn't sent."""
    _import_with_status_history(client, auth_headers, "hist-1", [], status="В работе")
    _import_with_status_history(client, auth_headers, "hist-2", [], status="Закрыт")

    work_order = _get_work_order(db_session, "HIST-0001")
    assert work_order.status == "Закрыт"  # the current-status field still updates as normal
    assert _status_history(db_session, work_order.id) == []


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


def _bulk_records(prefix: str, count: int) -> list[dict]:
    return [
        {
            "number": f"{prefix}-{i:05d}",
            "date": "2026-09-12T18:38:09",
            "customer": "Bulk Customer",
            "car": "VIN",
            "amount": 100,
        }
        for i in range(count)
    ]


VIN_A = "WVWZZZ1JZXW000001"
VIN_B = "WVWZZZ1JZXW000002"


def _wo_record(number, *, vin=None, repair_type=None, organization=None, payer=None) -> dict:
    """One work order record, for exercising is_internal recomputation -
    see services/internal_order_rules.py."""
    return {
        "number": number,
        "date": "2026-09-18T06:00:00",
        "customer": "Test Customer",
        "payer": payer,
        "car": "VW TIGUAN",
        "vin": vin,
        "amount": 1000,
        "repair_type": repair_type,
        "organization": organization,
    }


def _import_records(client, auth_headers, batch_id, records) -> None:
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-18T06:00:00",
        "batch_id": batch_id,
        "records": records,
    }
    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)
    assert response.status_code == 200


def test_internal_flag_true_for_allowed_org_with_external_sibling(
    client, db_session, auth_headers
) -> None:
    _import_records(
        client,
        auth_headers,
        "internal-1",
        [
            _wo_record("EXT-1", vin=VIN_A, repair_type="Страховой"),
            _wo_record("INT-1", vin=VIN_A, repair_type="ТО", organization="ПАН-МОТОРС, ООО"),
        ],
    )

    assert _get_work_order(db_session, "INT-1").is_internal is True
    # The external sibling itself is never "внутренний".
    assert _get_work_order(db_session, "EXT-1").is_internal is False


def test_internal_flag_false_without_an_external_sibling(client, db_session, auth_headers) -> None:
    _import_records(
        client,
        auth_headers,
        "internal-2",
        [_wo_record("INT-2", vin=VIN_A, repair_type="ТО", organization="ПАН-МОТОРС, ООО")],
    )

    assert _get_work_order(db_session, "INT-2").is_internal is False


def test_internal_flag_false_for_a_disallowed_organization(
    client, db_session, auth_headers
) -> None:
    _import_records(
        client,
        auth_headers,
        "internal-3",
        [
            _wo_record("EXT-3", vin=VIN_A, repair_type="Страховой"),
            _wo_record("INT-3", vin=VIN_A, repair_type="ТО", organization="ООО Совсем Другое"),
        ],
    )

    assert _get_work_order(db_session, "INT-3").is_internal is False


def test_internal_flag_pan_stanislav_requires_a_non_physical_payer(
    client, db_session, auth_headers
) -> None:
    _import_records(
        client,
        auth_headers,
        "internal-4",
        [
            _wo_record("EXT-4", vin=VIN_A, repair_type="Страховой"),
            _wo_record(
                "INT-4A",
                vin=VIN_A,
                repair_type="ТО",
                organization="ИП ПАН СТАНИСЛАВ ВЯЧЕСЛАВОВИЧ",
                payer="Иванов Иван Иванович",
            ),
            _wo_record(
                "INT-4B",
                vin=VIN_A,
                repair_type="ТО",
                organization="ИП ПАН СТАНИСЛАВ ВЯЧЕСЛАВОВИЧ",
                payer="ООО Ромашка",
            ),
        ],
    )

    assert _get_work_order(db_session, "INT-4A").is_internal is False
    assert _get_work_order(db_session, "INT-4B").is_internal is True


def test_internal_flag_ignored_without_a_valid_vin(client, db_session, auth_headers) -> None:
    """Same "Автомобиль" text as the external sibling, but no VIN - must
    NOT be matched by text fallback (see internal_order_rules module
    docstring: car matching is VIN-only now)."""
    _import_records(
        client,
        auth_headers,
        "internal-5",
        [
            _wo_record("EXT-5", vin=VIN_A, repair_type="Страховой"),
            _wo_record("INT-5", vin=None, repair_type="ТО", organization="ПАН-МОТОРС, ООО"),
        ],
    )

    assert _get_work_order(db_session, "INT-5").is_internal is False


def test_internal_flag_recomputed_when_external_sibling_arrives_later(
    client, db_session, auth_headers
) -> None:
    _import_records(
        client,
        auth_headers,
        "internal-6a",
        [_wo_record("INT-6", vin=VIN_A, repair_type="ТО", organization="ПАН-МОТОРС, ООО")],
    )
    assert _get_work_order(db_session, "INT-6").is_internal is False

    _import_records(
        client,
        auth_headers,
        "internal-6b",
        [_wo_record("EXT-6", vin=VIN_A, repair_type="Страховой")],
    )

    assert _get_work_order(db_session, "INT-6").is_internal is True


def test_internal_flag_does_not_affect_a_different_car(client, db_session, auth_headers) -> None:
    _import_records(
        client,
        auth_headers,
        "internal-7",
        [
            _wo_record("EXT-7", vin=VIN_A, repair_type="Страховой"),
            _wo_record("INT-7", vin=VIN_A, repair_type="ТО", organization="ПАН-МОТОРС, ООО"),
            _wo_record("OTHER-7", vin=VIN_B, repair_type="ТО", organization="ПАН-МОТОРС, ООО"),
        ],
    )

    assert _get_work_order(db_session, "INT-7").is_internal is True
    # VIN_B has no external sibling at all - untouched by VIN_A's grouping.
    assert _get_work_order(db_session, "OTHER-7").is_internal is False


def test_import_stores_vin(client, db_session, auth_headers) -> None:
    _import_records(client, auth_headers, "vin-1", [_wo_record("VIN-TEST-1", vin=VIN_A)])

    assert _get_work_order(db_session, "VIN-TEST-1").vin == VIN_A


def test_import_accepts_missing_vin_as_null(client, db_session, auth_headers) -> None:
    _import_records(client, auth_headers, "vin-2", [_wo_record("VIN-TEST-2", vin=None)])

    work_order = _get_work_order(db_session, "VIN-TEST-2")
    assert work_order.vin is None
    assert work_order.car_key is None


def test_import_processes_more_than_one_chunk(client, db_session, auth_headers) -> None:
    """A payload larger than CHUNK_SIZE must still fully apply, split across
    multiple committed chunks (see process_work_order_import)."""
    total = import_service.CHUNK_SIZE + 10
    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-13T10:00:00",
        "batch_id": f"test-multichunk-{uuid.uuid4()}",
        "records": _bulk_records("MULTI", total),
    }

    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["received"] == total
    assert body["inserted"] == total
    assert body["updated"] == 0

    rows = (
        db_session.execute(select(WorkOrder).where(WorkOrder.external_number.like("MULTI-%")))
        .scalars()
        .all()
    )
    assert len(rows) == total

    batch = db_session.execute(
        select(ImportBatch).where(ImportBatch.batch_id == payload["batch_id"])
    ).scalar_one()
    assert batch.status == "success"
    assert batch.records_inserted == total
    assert batch.error_message is None


def test_import_chunk_failure_does_not_roll_back_earlier_committed_chunks(
    client, db_session, auth_headers, monkeypatch
) -> None:
    """One chunk failing partway through a large import must not undo
    chunks that already committed successfully before it - each chunk is
    its own transaction (see process_work_order_import's CHUNK_SIZE
    docstring), unlike the old single-transaction-for-everything design."""
    chunk_size = import_service.CHUNK_SIZE
    total = chunk_size + 5
    failing_number = f"CHUNK-{chunk_size:05d}"  # first record of the 2nd chunk

    original_replace = import_service._replace_line_items

    def _replace_or_fail(db, work_order_id, record):
        if record.number == failing_number:
            raise RuntimeError("simulated failure")
        return original_replace(db, work_order_id, record)

    monkeypatch.setattr(import_service, "_replace_line_items", _replace_or_fail)

    payload = {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-13T10:00:00",
        "batch_id": f"test-chunkfail-{uuid.uuid4()}",
        "records": _bulk_records("CHUNK", total),
    }

    response = client.post(IMPORT_URL, json=payload, headers=auth_headers)
    assert response.status_code == 500

    rows = (
        db_session.execute(select(WorkOrder).where(WorkOrder.external_number.like("CHUNK-%")))
        .scalars()
        .all()
    )
    numbers = {row.external_number for row in rows}
    assert numbers == {f"CHUNK-{i:05d}" for i in range(chunk_size)}
    assert failing_number not in numbers

    batch = db_session.execute(
        select(ImportBatch).where(ImportBatch.batch_id == payload["batch_id"])
    ).scalar_one()
    assert batch.status == "failed"
    assert batch.records_inserted == chunk_size
    assert batch.error_message is not None
    assert "simulated failure" in batch.error_message
