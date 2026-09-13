from decimal import Decimal

from sqlalchemy import select

from app.models.import_batch import ImportBatch
from app.models.work_order import WorkOrder

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
