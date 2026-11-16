"""Доска задач CRM (services/crm_task_service.py и /api/v1/crm-tasks): взятие телефона на
контроль со звонка, переходы между столбцами по планировщику/заявке/заказ-наряду, «позже звонка»,
ручной «Отказ», сроки окраски и счётчик по цеху."""

import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.body_car import BodyCar
from app.models.body_car_stage import BodyCarStage
from app.models.call_record import CallRecord
from app.models.crm_task import CrmTask
from app.models.department import Department
from app.models.employee import Employee
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop
from app.services import crm_task_service as service

PHONE = "9001112233"
RAW_PHONE = "+7 (900) 111-22-33"


def _now() -> datetime:
    return datetime.now(UTC)


def _workshop(db: Session, workshop_type: str = "Кузовной", name: str = "Каховка") -> Workshop:
    from datetime import time

    department = Department(name=name)
    db.add(department)
    db.flush()
    workshop = Workshop(
        department_id=department.id,
        workshop_type=workshop_type,
        posts_count=1,
        start_time=time(8),
        end_time=time(20),
        working_days=[0, 1, 2, 3, 4],
    )
    db.add(workshop)
    db.commit()
    return workshop


def _call(
    db: Session, *, at: datetime, phone: str | None = PHONE, workshop_id: uuid.UUID | None = None
) -> CallRecord:
    call = CallRecord(
        provider="zeon",
        external_id=str(uuid.uuid4()),
        call_date=at.date(),
        occurred_at=at,
        call_type="IN",
        client=phone,
        workshop_id=workshop_id,
        wait_sec=3,
        talk_sec=60,
        answered=True,
    )
    db.add(call)
    db.commit()
    return call


def _task(db: Session, call: CallRecord, workshop_id: uuid.UUID | None = None) -> CrmTask:
    """Takes the call under control; the цех is the given one, else the call's own, else a
    fresh one (a цех is mandatory)."""
    workshop_id = workshop_id or call.workshop_id
    if workshop_id is None:
        workshop_id = _workshop(db, "Слесарный", f"Цех-{uuid.uuid4().hex[:6]}").id
    task, created = service.create_from_call(
        db, call.id, workshop_id=workshop_id, actor_id=None, actor_name="Тест"
    )
    assert created
    return task


def _body_car(
    db: Session,
    workshop: Workshop,
    *,
    created_at: datetime,
    stage: str = "Осмотр",
    phone: str | None = RAW_PHONE,
) -> BodyCar:
    car = BodyCar(
        workshop_id=workshop.id,
        car_description="Opel Astra",
        phone=phone,
        client_name="Иванов",
        color="#93c5fd",
        created_at=created_at,
    )
    db.add(car)
    db.flush()
    db.add(
        BodyCarStage(
            body_car_id=car.id,
            stage_name=stage,
            start_date=date(2026, 11, 16),
            end_date=date(2026, 11, 16),
            sort_order=0,
        )
    )
    db.commit()
    return car


def _document(
    db: Session, *, doc_type: str, created: datetime, phone: str | None = RAW_PHONE, number=None
) -> WorkOrder:
    doc = WorkOrder(
        external_number=number or f"НОМ{uuid.uuid4().hex[:6]}",
        source_system="alpha-auto-repair_request" if doc_type == "repair_request" else "alpha-auto",
        doc_type=doc_type,
        document_date=created,
        created_date=created,
        phone=phone,
        customer_name="Клиент",
        amount=Decimal("0"),
    )
    db.add(doc)
    db.commit()
    return doc


def _status(db: Session, task: CrmTask) -> str:
    service.sync_tasks(db)
    db.refresh(task)
    return task.status


# ---- создание ------------------------------------------------------------------


def test_call_becomes_a_task_in_the_control_column(db_session) -> None:
    workshop = _workshop(db_session)
    call = _call(db_session, at=_now() - timedelta(hours=1), workshop_id=workshop.id)
    task = _task(db_session, call)
    assert task.status == "control"
    assert task.phone == PHONE
    assert task.workshop_id == workshop.id
    assert task.call_at == call.occurred_at


def test_same_phone_is_not_taken_twice_while_it_is_active(db_session) -> None:
    workshop = _workshop(db_session)
    first = _task(db_session, _call(db_session, at=_now() - timedelta(hours=2)), workshop.id)
    again, created = service.create_from_call(
        db_session,
        _call(db_session, at=_now() - timedelta(hours=1)).id,
        workshop_id=workshop.id,
        actor_id=None,
        actor_name="Тест",
    )
    assert not created
    assert again.id == first.id


def test_phone_can_be_taken_again_after_a_refusal(db_session) -> None:
    first = _task(db_session, _call(db_session, at=_now() - timedelta(hours=2)))
    service.move_task(db_session, first.id, "refused", reason="Дорого", actor_name="Тест")
    second = _task(db_session, _call(db_session, at=_now() - timedelta(hours=1)))
    assert second.id != first.id


def test_a_call_without_a_client_number_cannot_be_taken(db_session) -> None:
    workshop = _workshop(db_session)
    call = _call(db_session, at=_now(), phone=None)
    with pytest.raises(service.CrmTaskInvalid):
        service.create_from_call(
            db_session, call.id, workshop_id=workshop.id, actor_id=None, actor_name="Тест"
        )


def test_a_workshop_is_mandatory_even_when_the_call_has_one(db_session) -> None:
    workshop = _workshop(db_session)
    call = _call(db_session, at=_now(), workshop_id=workshop.id)
    with pytest.raises(service.CrmTaskInvalid, match="цех"):
        service.create_from_call(
            db_session, call.id, workshop_id=None, actor_id=None, actor_name="Тест"
        )
    with pytest.raises(service.CrmTaskInvalid):
        service.create_from_call(
            db_session, call.id, workshop_id=uuid.uuid4(), actor_id=None, actor_name="Тест"
        )


def test_the_chosen_workshop_wins_over_the_calls_own(db_session) -> None:
    from_call = _workshop(db_session, "Слесарный", "Каховка-2")
    chosen = _workshop(db_session, "Кузовной", "Каховка")
    call = _call(db_session, at=_now(), workshop_id=from_call.id)
    assert _task(db_session, call, chosen.id).workshop_id == chosen.id


def test_old_refused_and_work_order_cards_go_to_the_archive(db_session) -> None:
    from app.services.settings_service import get_app_settings

    workshop = _workshop(db_session)
    old_refused = _task(db_session, _call(db_session, at=_now(), phone="9001000001"), workshop.id)
    fresh_refused = _task(db_session, _call(db_session, at=_now(), phone="9001000002"), workshop.id)
    old_control = _task(db_session, _call(db_session, at=_now(), phone="9001000003"), workshop.id)
    for task in (old_refused, fresh_refused):
        service.move_task(db_session, task.id, "refused", reason="Дорого", actor_name="Тест")
    old_refused.status_changed_at = _now() - timedelta(days=31)
    old_control.status_changed_at = _now() - timedelta(days=90)  # активная - не архивируется
    db_session.commit()

    ids = {t.id for t in service.list_tasks(db_session)}
    assert ids == {fresh_refused.id, old_control.id}
    everything = {t.id for t in service.list_tasks(db_session, include_archived=True)}
    assert everything == {old_refused.id, fresh_refused.id, old_control.id}

    get_app_settings(db_session).crm_task_archive_days = 100  # срок архива - параметр
    db_session.commit()
    assert old_refused.id in {t.id for t in service.list_tasks(db_session)}


# ---- автоматика: осмотр -> думает -> заказ-наряд ------------------------------------


def test_planner_inspection_after_the_call_moves_to_inspection(db_session) -> None:
    workshop = _workshop(db_session)
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=3)))
    _body_car(db_session, workshop, created_at=_now() - timedelta(hours=1))
    assert _status(db_session, task) == "inspection"
    assert task.car_description == "Opel Astra"
    assert task.client_name == "Иванов"


def test_planner_record_before_the_call_or_other_stage_or_phone_is_ignored(db_session) -> None:
    workshop = _workshop(db_session)
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=3)))
    _body_car(db_session, workshop, created_at=_now() - timedelta(hours=5))  # до звонка
    _body_car(db_session, workshop, created_at=_now() - timedelta(hours=1), stage="Приёмка")
    other_phone = "+7 900 999-99-99"
    _body_car(db_session, workshop, created_at=_now() - timedelta(hours=1), phone=other_phone)
    assert _status(db_session, task) == "control"


def test_repair_request_moves_only_from_inspection(db_session) -> None:
    workshop = _workshop(db_session)
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=6)))
    _document(db_session, doc_type="repair_request", created=_now() - timedelta(hours=5))
    assert _status(db_session, task) == "control"  # без осмотра заявка не двигает

    _body_car(db_session, workshop, created_at=_now() - timedelta(hours=4))
    assert _status(db_session, task) == "inspection"  # заявка была раньше осмотра - не считается

    request = _document(
        db_session, doc_type="repair_request", created=_now() - timedelta(hours=1), number="ЭП-1"
    )
    assert _status(db_session, task) == "thinking"
    assert task.request_number == request.external_number


def test_work_order_moves_from_any_active_column(db_session) -> None:
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=3)))
    order = _document(
        db_session, doc_type="work_order", created=_now() - timedelta(hours=1), number="ЭП-77"
    )
    assert _status(db_session, task) == "work_order"
    assert task.work_order_number == order.external_number


def test_work_order_before_the_call_is_ignored(db_session) -> None:
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=3)))
    _document(db_session, doc_type="work_order", created=_now() - timedelta(days=30))
    assert _status(db_session, task) == "control"


def test_a_repair_request_is_not_taken_for_a_work_order(db_session) -> None:
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=3)))
    _document(db_session, doc_type="repair_request", created=_now() - timedelta(hours=1))
    assert _status(db_session, task) == "control"


def test_full_path_in_one_sync(db_session) -> None:
    workshop = _workshop(db_session)
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=9)))
    _body_car(db_session, workshop, created_at=_now() - timedelta(hours=6))
    _document(db_session, doc_type="repair_request", created=_now() - timedelta(hours=4))
    assert _status(db_session, task) == "thinking"
    _document(db_session, doc_type="work_order", created=_now() - timedelta(hours=1))
    assert _status(db_session, task) == "work_order"


# ---- ручные перемещения --------------------------------------------------------------


def test_refusal_needs_a_reason(db_session) -> None:
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=1)))
    with pytest.raises(service.CrmTaskInvalid):
        service.move_task(db_session, task.id, "refused", reason="  ", actor_name="Тест")
    moved = service.move_task(db_session, task.id, "refused", reason="Дорого", actor_name="Тест")
    assert moved.status == "refused"
    assert moved.refuse_reason == "Дорого"


def test_refused_task_is_left_alone_by_the_automation(db_session) -> None:
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=3)))
    service.move_task(db_session, task.id, "refused", reason="Дорого", actor_name="Тест")
    _document(db_session, doc_type="work_order", created=_now() + timedelta(seconds=5))
    assert _status(db_session, task) == "refused"


def test_by_hand_only_to_refusal_and_back_to_control(db_session) -> None:
    workshop = _workshop(db_session)
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=5)))
    for target in ("inspection", "thinking", "work_order"):
        with pytest.raises(service.CrmTaskInvalid):
            service.move_task(db_session, task.id, target, reason=None, actor_name="Тест")

    # В «Отказ» - из любого столбца, в том числе из автоматических.
    _body_car(db_session, workshop, created_at=_now() - timedelta(hours=3))
    assert _status(db_session, task) == "inspection"
    service.move_task(db_session, task.id, "refused", reason="Дорого", actor_name="Тест")
    assert _status(db_session, task) == "refused"

    # Из «Отказа» - только в «На контроле».
    for target in ("inspection", "thinking", "work_order"):
        with pytest.raises(service.CrmTaskInvalid):
            service.move_task(db_session, task.id, target, reason=None, actor_name="Тест")
    service.move_task(db_session, task.id, "control", reason=None, actor_name="Тест")
    assert _status(db_session, task) == "control"  # старая запись больше не цепляется
    assert task.car_description is None
    assert task.inspection_date is None


def test_work_order_card_can_still_be_refused_and_returned(db_session) -> None:
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=3)))
    _document(db_session, doc_type="work_order", created=_now() - timedelta(hours=1), number="ЭП-5")
    assert _status(db_session, task) == "work_order"
    service.move_task(db_session, task.id, "refused", reason="Передумал", actor_name="Тест")
    moved = service.move_task(db_session, task.id, "control", reason=None, actor_name="Тест")
    assert moved.status == "control"
    assert moved.work_order_number is None


# ---- создание сразу в нужном столбце --------------------------------------------------


def test_created_straight_into_inspection_with_the_dates(db_session) -> None:
    workshop = _workshop(db_session)
    call = _call(db_session, at=_now() - timedelta(hours=3))
    car = _body_car(db_session, workshop, created_at=_now() - timedelta(hours=1))
    task = _task(db_session, call, workshop.id)
    assert task.status == "inspection"
    assert task.inspection_at is not None
    assert (task.inspection_date, task.inspection_end_date) == (date(2026, 11, 16),) * 2
    assert task.car_description == car.car_description


def test_created_straight_into_thinking_and_work_order(db_session) -> None:
    workshop = _workshop(db_session)
    call = _call(db_session, at=_now() - timedelta(hours=9))
    _body_car(db_session, workshop, created_at=_now() - timedelta(hours=6))
    _document(
        db_session, doc_type="repair_request", created=_now() - timedelta(hours=4), number="ЗР-9"
    )
    task = _task(db_session, call, workshop.id)
    assert (task.status, task.request_number) == ("thinking", "ЗР-9")

    # Заказ-наряд после звонка - сразу «Заказ-наряд» (отдельный телефон).
    other = "+7 911 222-33-44"
    call2 = _call(db_session, at=_now() - timedelta(hours=3), phone="9112223344")
    _document(db_session, doc_type="work_order", created=_now() - timedelta(hours=1), phone=other)
    assert _task(db_session, call2, workshop.id).status == "work_order"


def test_earlier_events_do_not_place_a_new_card(db_session) -> None:
    workshop = _workshop(db_session)
    call = _call(db_session, at=_now() - timedelta(hours=1))
    _body_car(db_session, workshop, created_at=_now() - timedelta(hours=5))
    _document(db_session, doc_type="work_order", created=_now() - timedelta(days=2))
    assert _task(db_session, call, workshop.id).status == "control"


# ---- окраска и счётчик ------------------------------------------------------------


def _aged(db: Session, task: CrmTask, days: float) -> None:
    task.status_changed_at = _now() - timedelta(days=days)
    db.commit()


def test_alert_thresholds_come_from_settings(db_session) -> None:
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=1)))
    now = _now()
    _aged(db_session, task, 0.5)
    assert service.alert_for(task, 1, 3, now) is None
    _aged(db_session, task, 1.5)
    assert service.alert_for(task, 1, 3, now) == "warn"
    _aged(db_session, task, 3.5)
    assert service.alert_for(task, 1, 3, now) == "overdue"
    assert service.alert_for(task, 5, 9, now) is None  # пороги - параметры


def test_only_the_control_column_is_coloured(db_session) -> None:
    workshop = _workshop(db_session)
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=3)))
    _body_car(db_session, workshop, created_at=_now() - timedelta(hours=1))
    assert _status(db_session, task) == "inspection"
    _aged(db_session, task, 10)
    assert service.alert_for(task, 1, 3, _now()) is None
    service.move_task(db_session, task.id, "refused", reason="Дорого", actor_name="Тест")
    _aged(db_session, task, 10)
    assert service.alert_for(task, 1, 3, _now()) is None


def test_overdue_counter_is_per_workshop(db_session) -> None:
    mine = _workshop(db_session, "Кузовной", "Каховка")
    other = _workshop(db_session, "Слесарный", "Каховка-2")
    a = _task(db_session, _call(db_session, at=_now(), phone="9001000001", workshop_id=mine.id))
    b = _task(db_session, _call(db_session, at=_now(), phone="9001000002", workshop_id=mine.id))
    c = _task(db_session, _call(db_session, at=_now(), phone="9001000003", workshop_id=other.id))
    d = _task(db_session, _call(db_session, at=_now(), phone="9001000004", workshop_id=mine.id))
    _aged(db_session, a, 1.5)  # розовая
    _aged(db_session, b, 4)  # красная
    _aged(db_session, c, 4)  # чужой цех
    _aged(db_session, d, 0.2)  # свежая

    result = service.overdue_count(db_session, workshop_id=mine.id)
    assert (result.warn_count, result.overdue_count) == (2, 1)
    assert service.overdue_count(db_session).warn_count == 3  # все цеха


# ---- API -----------------------------------------------------------------------------


def test_api_flow(client, db_session, auth_headers) -> None:
    workshop = _workshop(db_session)
    call = _call(db_session, at=_now() - timedelta(hours=1), workshop_id=workshop.id)
    headers = {**auth_headers, "X-Actor-Name": "%D0%A2%D0%B5%D1%81%D1%82"}

    without_workshop = client.post(
        "/api/v1/crm-tasks", json={"call_id": str(call.id)}, headers=headers
    )
    assert without_workshop.status_code == 422

    payload = {"call_id": str(call.id), "workshop_id": str(workshop.id)}
    created = client.post("/api/v1/crm-tasks", json=payload, headers=headers)
    assert created.status_code == 200
    body = created.json()
    assert body["created"] is True
    assert body["task"]["status"] == "control"
    assert body["task"]["created_by_name"] == "Тест"
    assert body["task"]["workshop_label"] == "Каховка — Кузовной"
    task_id = body["task"]["id"]

    again = client.post("/api/v1/crm-tasks", json=payload, headers=headers)
    assert again.json()["created"] is False

    listing = client.get(f"/api/v1/crm-tasks?workshop_id={workshop.id}", headers=headers).json()
    assert [t["id"] for t in listing["items"]] == [task_id]
    assert (listing["warn_days"], listing["overdue_days"]) == (1, 3)

    no_reason = client.post(
        f"/api/v1/crm-tasks/{task_id}/move", json={"status": "refused"}, headers=headers
    )
    assert no_reason.status_code == 422
    moved = client.post(
        f"/api/v1/crm-tasks/{task_id}/move",
        json={"status": "refused", "reason": "Дорого"},
        headers=headers,
    )
    assert moved.status_code == 200
    assert moved.json()["refuse_reason"] == "Дорого"

    count = client.get("/api/v1/crm-tasks/overdue-count", headers=headers).json()
    assert count["count"] == 0


def test_settings_carry_the_thresholds(client, auth_headers) -> None:
    current = client.get("/api/v1/settings", headers=auth_headers).json()
    assert (current["crm_task_warn_days"], current["crm_task_overdue_days"]) == (1, 3)

    assert current["crm_task_archive_days"] == 30

    payload = {"crm_task_warn_days": 2, "crm_task_overdue_days": 5, "crm_task_archive_days": 14}
    saved = client.put("/api/v1/settings", json=payload, headers=auth_headers).json()
    assert (saved["crm_task_warn_days"], saved["crm_task_overdue_days"]) == (2, 5)
    assert saved["crm_task_archive_days"] == 14

    bad = client.put(
        "/api/v1/settings",
        json={"crm_task_warn_days": 4, "crm_task_overdue_days": 2},
        headers=auth_headers,
    )
    assert bad.status_code == 422


def test_detail_has_links_comments_and_the_refusal_reason(client, db_session, auth_headers) -> None:
    workshop = _workshop(db_session)
    call = _call(db_session, at=_now() - timedelta(hours=1), workshop_id=workshop.id)
    task = _task(db_session, call, workshop.id)
    headers = {**auth_headers, "X-Actor-Name": "%D0%A2%D0%B5%D1%81%D1%82"}
    url = f"/api/v1/crm-tasks/{task.id}"

    empty = client.get(url, headers=headers).json()
    assert empty["comments"] == []
    assert (empty["request_id"], empty["work_order_id"]) == (None, None)
    assert empty["task"]["comments_count"] == 0

    blank = client.post(f"{url}/comments", json={"text": "  "}, headers=headers)
    assert blank.status_code == 422
    first = client.post(f"{url}/comments", json={"text": "Перезвонить завтра"}, headers=headers)
    assert first.status_code == 200
    assert first.json()["author_name"] == "Тест"
    assert first.json()["status"] == "control"

    refused = client.post(
        f"{url}/move", json={"status": "refused", "reason": "Дорого"}, headers=headers
    )
    assert refused.json()["comments_count"] == 2
    # Комментарии можно оставлять и в «Отказе».
    client.post(f"{url}/comments", json={"text": "Звонили ещё раз"}, headers=headers)

    detail = client.get(url, headers=headers).json()
    assert [c["text"] for c in detail["comments"]] == [
        "Звонили ещё раз",
        "Отказ: Дорого",
        "Перезвонить завтра",
    ]
    assert detail["comments"][0]["status"] == "refused"
    assert detail["task"]["refuse_reason"] == "Дорого"
    listing = client.get("/api/v1/crm-tasks", headers=headers).json()
    assert listing["items"][0]["comments_count"] == 3

    assert client.get(f"/api/v1/crm-tasks/{uuid.uuid4()}", headers=headers).status_code == 404
    unknown = f"/api/v1/crm-tasks/{uuid.uuid4()}/comments"
    missing = client.post(unknown, json={"text": "x"}, headers=headers)
    assert missing.status_code == 404


def test_detail_links_to_the_request_and_the_work_order(client, db_session, auth_headers) -> None:
    workshop = _workshop(db_session)
    call = _call(db_session, at=_now() - timedelta(hours=1), workshop_id=workshop.id)
    task = _task(db_session, call, workshop.id)
    request = _document(db_session, doc_type="repair_request", created=_now(), number="ЗР-1")
    order = _document(db_session, doc_type="work_order", created=_now(), number="ЗН-1")
    task.request_number, task.work_order_number = "ЗР-1", "ЗН-1"
    db_session.commit()

    detail = client.get(f"/api/v1/crm-tasks/{task.id}", headers=auth_headers).json()
    assert detail["request_id"] == str(request.id)
    assert detail["work_order_id"] == str(order.id)


def _employee(db: Session, workshop: Workshop, name: str = "Петров П.П.") -> Employee:
    employee = Employee(full_name=name, specialty="Мастер", workshop_id=workshop.id)
    db.add(employee)
    db.commit()
    return employee


def test_employee_must_work_in_the_chosen_workshop(db_session) -> None:
    mine = _workshop(db_session, "Кузовной", "Каховка")
    other = _workshop(db_session, "Слесарный", "Север")
    stranger = _employee(db_session, other, "Чужой Ч.Ч.")
    call = _call(db_session, at=_now() - timedelta(hours=1))
    with pytest.raises(service.CrmTaskInvalid):
        service.create_from_call(
            db_session,
            call.id,
            workshop_id=mine.id,
            employee_id=stranger.id,
            actor_id=None,
            actor_name="Тест",
        )
    with pytest.raises(service.CrmTaskInvalid):
        service.create_from_call(
            db_session,
            call.id,
            workshop_id=mine.id,
            employee_id=uuid.uuid4(),
            actor_id=None,
            actor_name="Тест",
        )


def test_board_filters_by_employee(client, db_session, auth_headers) -> None:
    workshop = _workshop(db_session)
    petrov = _employee(db_session, workshop, "Петров П.П.")
    sidorov = _employee(db_session, workshop, "Сидоров С.С.")
    calls = [
        _call(db_session, at=_now() - timedelta(hours=2), phone="9001112233"),
        _call(db_session, at=_now() - timedelta(hours=2), phone="9004445566"),
        _call(db_session, at=_now() - timedelta(hours=2), phone="9007778899"),
    ]
    for call, employee in zip(calls, (petrov, sidorov, None), strict=True):
        payload = {"call_id": str(call.id), "workshop_id": str(workshop.id)}
        if employee:
            payload["employee_id"] = str(employee.id)
        created = client.post("/api/v1/crm-tasks", json=payload, headers=auth_headers)
        assert created.status_code == 200
    assert created.json()["task"]["employee_name"] is None

    everyone = client.get("/api/v1/crm-tasks", headers=auth_headers).json()["items"]
    assert len(everyone) == 3
    mine = client.get(f"/api/v1/crm-tasks?employee_id={petrov.id}", headers=auth_headers).json()[
        "items"
    ]
    assert [(t["phone"], t["employee_name"]) for t in mine] == [("9001112233", "Петров П.П.")]

    wrong = client.post(
        "/api/v1/crm-tasks",
        json={
            "call_id": str(_call(db_session, at=_now(), phone="9000000001").id),
            "workshop_id": str(workshop.id),
            "employee_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert wrong.status_code == 422


# ---- «Запланировать действие» ---------------------------------------------------------


def _msk(day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone(timedelta(hours=3)))


def test_colours_count_from_the_latest_planned_date(db_session) -> None:
    task = _task(db_session, _call(db_session, at=_now() - timedelta(days=5)))
    _aged(db_session, task, 10)  # без плана давно красная
    assert service.alert_for(task, 1, 3, _now()) == "overdue"

    # Контакт на 17.11: до конца 17.11 белая, с 18.11 розовая, с 20.11 красная.
    service.add_comment(
        db_session,
        task.id,
        "Перезвонить по цене",
        next_action_date=date(2026, 11, 17),
        actor_id=None,
        actor_name="Тест",
    )
    assert service.alert_for(task, 1, 3, _msk(16, 12)) is None
    assert service.alert_for(task, 1, 3, _msk(17, 23, 59)) is None
    assert service.alert_for(task, 1, 3, _msk(18, 0, 0)) == "warn"
    assert service.alert_for(task, 1, 3, _msk(19, 12)) == "warn"
    assert service.alert_for(task, 1, 3, _msk(20, 0, 0)) == "overdue"

    # 20.11 действие перенесли на 25.11: снова белая до конца 25.11, розовая с 26.11.
    service.add_comment(
        db_session,
        task.id,
        "Клиент попросил позвонить позже",
        next_action_date=date(2026, 11, 25),
        actor_id=None,
        actor_name="Тест",
    )
    assert service.alert_for(task, 1, 3, _msk(20, 10)) is None
    assert service.alert_for(task, 1, 3, _msk(25, 23, 59)) is None
    assert service.alert_for(task, 1, 3, _msk(26, 0, 0)) == "warn"


def test_a_planned_action_needs_a_comment(client, db_session, auth_headers) -> None:
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=1)))
    url = f"/api/v1/crm-tasks/{task.id}/comments"
    with pytest.raises(service.CrmTaskInvalid):
        service.add_comment(
            db_session,
            task.id,
            "  ",
            next_action_date=date(2026, 11, 20),
            actor_id=None,
            actor_name="Тест",
        )
    blank = client.post(
        url, json={"text": "", "next_action_date": "2026-11-20"}, headers=auth_headers
    )
    assert blank.status_code == 422
    assert "комментарий" in blank.json()["detail"].lower()
    db_session.refresh(task)
    assert task.next_action_date is None

    ok = client.post(
        url,
        json={"text": "Позвонить во вторник", "next_action_date": "2026-11-17"},
        headers=auth_headers,
    )
    assert ok.status_code == 200


def test_detail_lists_the_history_of_planned_actions(client, db_session, auth_headers) -> None:
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=1)))
    url = f"/api/v1/crm-tasks/{task.id}"
    client.post(
        f"{url}/comments", json={"text": "просто заметка"}, headers=auth_headers
    )  # без даты - не действие
    client.post(
        f"{url}/comments",
        json={"text": "Первый план", "next_action_date": "2026-11-17"},
        headers=auth_headers,
    )
    client.post(
        f"{url}/comments",
        json={"text": "Перенос", "next_action_date": "2026-11-25"},
        headers=auth_headers,
    )
    detail = client.get(url, headers=auth_headers).json()
    assert detail["task"]["next_action_date"] == "2026-11-25"
    assert [(a["planned_date"], a["comment"]) for a in detail["actions"]] == [
        ("2026-11-25", "Перенос"),
        ("2026-11-17", "Первый план"),
    ]
    assert len(detail["comments"]) == 3  # каждый план - ещё и комментарий в истории


def test_planned_date_resets_when_the_card_returns_to_control(db_session) -> None:
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=1)))
    service.add_comment(
        db_session,
        task.id,
        "План",
        next_action_date=date(2026, 11, 17),
        actor_id=None,
        actor_name="Тест",
    )
    service.move_task(db_session, task.id, "refused", reason="Дорого", actor_name="Тест")
    moved = service.move_task(db_session, task.id, "control", reason=None, actor_name="Тест")
    assert moved.next_action_date is None


def test_counter_uses_the_planned_date(db_session) -> None:
    workshop = _workshop(db_session)
    task = _task(db_session, _call(db_session, at=_now() - timedelta(days=5)), workshop.id)
    _aged(db_session, task, 10)
    assert service.overdue_count(db_session, workshop_id=workshop.id).warn_count == 1
    service.add_comment(
        db_session,
        task.id,
        "Позвоню позже",
        next_action_date=(_now() + timedelta(days=3)).date(),
        actor_id=None,
        actor_name="Тест",
    )
    assert service.overdue_count(db_session, workshop_id=workshop.id).warn_count == 0


# ---- «Записан на осмотр» руками: запись в планировщике цеха карточки ------------------


def _manual_job(db: Session, workshop: Workshop, *, created_at: datetime):
    from datetime import time

    from app.models.workshop_job import WorkshopJob

    job = WorkshopJob(
        workshop_id=workshop.id,
        car_description="Kia Rio",
        phone=RAW_PHONE,
        job_date=date(2026, 11, 18),
        post_number=1,
        start_time=time(10),
        end_time=time(11),
        created_at=created_at,
    )
    db.add(job)
    db.commit()
    return job


def test_manual_move_to_inspection_links_a_body_car(db_session) -> None:
    workshop = _workshop(db_session)
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=1)), workshop.id)
    # Запись, созданная в диалоге доски: сразу ПОСЛЕ звонка, но без привязки по телефону.
    car = _body_car(db_session, workshop, created_at=_now(), phone="123")

    moved = service.move_task(
        db_session, task.id, "inspection", reason=None, body_car_id=car.id, actor_name="Тест"
    )

    assert moved.status == "inspection"
    assert moved.body_car_id == car.id
    assert moved.inspection_date == date(2026, 11, 16)
    assert moved.car_description == "Opel Astra"


def test_manual_move_to_inspection_needs_a_record_of_the_same_workshop(db_session) -> None:
    workshop = _workshop(db_session)
    other = _workshop(db_session, name="Другой")
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=1)), workshop.id)

    with pytest.raises(service.CrmTaskInvalid):
        service.move_task(db_session, task.id, "inspection", reason=None, actor_name="Тест")
    foreign = _body_car(db_session, other, created_at=_now())
    with pytest.raises(service.CrmTaskInvalid):
        service.move_task(
            db_session, task.id, "inspection", reason=None, body_car_id=foreign.id, actor_name="Т"
        )


def test_back_to_control_deletes_the_planner_record_but_refusal_keeps_it(db_session) -> None:
    workshop = _workshop(db_session)
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=1)), workshop.id)
    car = _body_car(db_session, workshop, created_at=_now(), phone="123")
    service.move_task(
        db_session, task.id, "inspection", reason=None, body_car_id=car.id, actor_name="Тест"
    )

    service.move_task(db_session, task.id, "control", reason=None, actor_name="Тест")
    db_session.expire_all()
    assert db_session.get(BodyCar, car.id) is None
    refreshed = db_session.get(CrmTask, task.id)
    assert refreshed.status == "control"
    assert refreshed.body_car_id is None and refreshed.inspection_date is None

    keep = _body_car(db_session, workshop, created_at=_now(), phone="123")
    service.move_task(
        db_session, task.id, "inspection", reason=None, body_car_id=keep.id, actor_name="Тест"
    )
    service.move_task(db_session, task.id, "refused", reason="Дорого", actor_name="Тест")
    service.move_task(db_session, task.id, "control", reason=None, actor_name="Тест")
    db_session.expire_all()
    assert db_session.get(BodyCar, keep.id) is not None


def test_manual_inspection_for_a_mechanical_workshop_uses_the_job(db_session) -> None:
    from app.models.workshop_job import WorkshopJob

    workshop = _workshop(db_session, "Слесарный")
    task = _task(db_session, _call(db_session, at=_now() - timedelta(hours=1)), workshop.id)
    job = _manual_job(db_session, workshop, created_at=_now())

    moved = service.move_task(
        db_session, task.id, "inspection", reason=None, workshop_job_id=job.id, actor_name="Тест"
    )
    assert moved.status == "inspection" and moved.inspection_date == date(2026, 11, 18)

    service.move_task(db_session, task.id, "control", reason=None, actor_name="Тест")
    db_session.expire_all()
    assert db_session.get(WorkshopJob, job.id) is None
