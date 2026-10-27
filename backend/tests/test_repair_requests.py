"""Repair requests (1C: Заявка на ремонт) are stored next to the work orders but
must stay out of every work-order figure."""

from sqlalchemy import func, select

from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLaborLine
from app.services.work_order_query_service import list_work_orders, monthly_summary

IMPORT_URL = "/api/v1/import/work-orders"
LIST_URL = "/api/v1/work-orders"


def _payload(records: list[dict]) -> dict:
    return {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-10-27T10:00:00",
        "batch_id": "requests-test-1",
        "records": records,
    }


WORK_ORDER = {
    "number": "ЭПЭП003194",
    "date": "2026-10-26T14:12:35",
    "closed_date": "2026-10-27T10:00:00",
    "status": "Закрыт",
    "customer": "Test Customer",
    "car": "SSANGYONG REXTON",
    "amount": 1000,
}
REQUEST = {
    "number": "ЭП00000465",
    "doc_type": "repair_request",
    "date": "2026-10-25T18:16:14",
    "closed_date": "2026-10-27T10:00:00",
    "status": "Подтверждено",
    "customer": "Test Customer",
    "car": "SSANGYONG REXTON",
    "amount": 34900,
    "linked_work_orders": ["ЭПЭП003194", "ЭПЭП003195"],
    "labor": [{"operation": "Арматурные работы", "price": 1500, "amount": 6000}],
}


def _import(client, auth_headers, records):
    response = client.post(IMPORT_URL, json=_payload(records), headers=auth_headers)
    assert response.status_code == 200, response.text


def test_request_is_stored_with_its_type_and_linked_work_orders(
    client, db_session, auth_headers
) -> None:
    _import(client, auth_headers, [WORK_ORDER, REQUEST])

    row = (
        db_session.execute(
            select(WorkOrder),
            execution_options={"include_repair_requests": True},
        )
        .scalars()
        .all()
    )
    by_number = {r.external_number: r for r in row}
    assert by_number["ЭПЭП003194"].doc_type == "work_order"
    assert by_number["ЭП00000465"].doc_type == "repair_request"
    assert by_number["ЭП00000465"].linked_work_orders == "ЭПЭП003194, ЭПЭП003195"
    assert by_number["ЭПЭП003194"].linked_work_orders is None
    assert len(db_session.execute(select(WorkOrderLaborLine)).scalars().all()) == 1


def test_requests_stay_out_of_every_work_order_query(client, db_session, auth_headers) -> None:
    _import(client, auth_headers, [WORK_ORDER, REQUEST])

    # plain ORM selects, a column aggregate and the revenue summary see work orders only
    assert [w.external_number for w in db_session.execute(select(WorkOrder)).scalars()] == [
        "ЭПЭП003194"
    ]
    assert db_session.execute(select(func.sum(WorkOrder.amount))).scalar_one() == 1000
    assert db_session.execute(select(func.count()).select_from(WorkOrder)).scalar_one() == 1
    summary = monthly_summary(db_session, revenue_statuses=["Закрыт"])
    assert [(row["work_order_count"], row["total_amount"]) for row in summary] == [(1, 1000)]

    items, total = list_work_orders(db_session)
    assert total == 1 and [i.external_number for i in items] == ["ЭПЭП003194"]


def test_list_shows_requests_only_when_asked_and_card_opens_them(
    client, db_session, auth_headers
) -> None:
    _import(client, auth_headers, [WORK_ORDER, REQUEST])

    plain = client.get(LIST_URL, headers=auth_headers).json()
    assert plain["total"] == 1

    full = client.get(LIST_URL, params={"include_requests": "true"}, headers=auth_headers).json()
    assert full["total"] == 2
    kinds = {item["external_number"]: item["doc_type"] for item in full["items"]}
    assert kinds == {"ЭПЭП003194": "work_order", "ЭП00000465": "repair_request"}

    request_id = next(i["id"] for i in full["items"] if i["doc_type"] == "repair_request")
    card = client.get(f"{LIST_URL}/{request_id}", headers=auth_headers)
    assert card.status_code == 200
    assert card.json()["doc_type"] == "repair_request"
    assert card.json()["linked_work_orders"] == "ЭПЭП003194, ЭПЭП003195"
    # only the linked work order that exists here (ЭПЭП003195 is not imported) gets a link
    work_order_id = next(i["id"] for i in full["items"] if i["doc_type"] == "work_order")
    assert card.json()["linked_work_order_refs"] == [
        {"id": work_order_id, "external_number": "ЭПЭП003194"}
    ]
    assert len(card.json()["labor"]) == 1


def test_request_and_work_order_with_the_same_number_do_not_overwrite_each_other(
    client, db_session, auth_headers
) -> None:
    # 1C numbers both kinds with the same prefixes/sequences (ПС..., СЛ...).
    work_order = {**WORK_ORDER, "number": "СЛ00000244", "amount": 1000}
    request = {**REQUEST, "number": "СЛ00000244", "amount": 178700}
    _import(client, auth_headers, [work_order, request])
    _import(client, auth_headers, [work_order, request])  # a re-import stays idempotent

    rows = (
        db_session.execute(select(WorkOrder), execution_options={"include_repair_requests": True})
        .scalars()
        .all()
    )
    assert sorted((r.doc_type, r.amount) for r in rows) == [
        ("repair_request", 178700),
        ("work_order", 1000),
    ]
