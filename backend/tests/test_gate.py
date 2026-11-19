"""Ворота кузовного цеха: заезд/выезд без остановки, много машин внутри, привязка к плану."""

import uuid
from datetime import UTC, datetime, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bay import BayIssue, GateStay
from app.models.body_car import BodyCar
from app.models.department import Department
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop
from app.services import bay_planner


def at(hour: int, minute: int = 0, second: int = 0, day: int = 2) -> datetime:
    return datetime(2026, 11, day, hour - 3, minute, second, tzinfo=UTC)


@pytest.fixture()
def workshop(db_session: Session) -> Workshop:
    department = Department(name="Каховка")
    db_session.add(department)
    db_session.flush()
    ws = Workshop(
        department_id=department.id,
        workshop_type="Кузовной",
        posts_count=1,
        start_time=time(8, 0),
        end_time=time(20, 0),
        working_days=[0, 1, 2, 3, 4],
    )
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture()
def gate_id(client: TestClient, auth_headers: dict, workshop: Workshop) -> str:
    response = client.post(
        "/api/v1/bays",
        json={
            "workshop_id": str(workshop.id),
            "name": "Ворота",
            "camera_code": "cam9",
            "kind": "gate",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    bays = response.json()["bays"]
    assert bays[0]["kind"] == "gate"
    return bays[0]["id"]


def _car(db: Session, workshop: Workshop, plate: str | None, **kw) -> BodyCar:
    car = BodyCar(workshop_id=workshop.id, plate=plate, color="#93c5fd", status="В работе", **kw)
    db.add(car)
    db.commit()
    return car


def _pass(client, headers, gate, kind, plate, when, confidence=0.9, **extra):
    body = {
        "event_type": kind,
        "plate": plate,
        "ocr_confidence": confidence,
        "occurred_at": when.isoformat(),
        **extra,
    }
    response = client.post(f"/api/v1/bays/{gate}/events", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _stays(client, headers, workshop, status="inside"):
    response = client.get(
        f"/api/v1/bays/gate/stays?workshop_id={workshop.id}&status={status}", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["stays"]


def test_several_cars_are_inside_at_once_and_each_exit_closes_its_own_car(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    for plate in ("А111АА77", "В222ВВ77", "С333СС77"):
        _car(db_session, workshop, plate)
    for minute, plate in enumerate(("А111АА77", "В222ВВ77", "С333СС77")):
        _pass(client, auth_headers, gate_id, "entry_confirmed", plate, at(9, minute * 10))
    assert {s["plate"] for s in _stays(client, auth_headers, workshop)} == {
        "А111АА77",
        "В222ВВ77",
        "С333СС77",
    }
    # Выезжает вторая, а первая и третья остаются.
    _pass(client, auth_headers, gate_id, "exit_confirmed", "В222ВВ77", at(12, 0))
    inside = {s["plate"] for s in _stays(client, auth_headers, workshop)}
    assert inside == {"А111АА77", "С333СС77"}
    cards = client.get(f"/api/v1/bays?workshop_id={workshop.id}", headers=auth_headers).json()
    assert cards["bays"][0]["inside_count"] == 2


def test_the_plan_card_is_marked_on_site_while_the_car_is_inside(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    car = _car(db_session, workshop, "А111АА77", car_description="Skoda")
    _pass(client, auth_headers, gate_id, "entry_confirmed", "А111АА77", at(9))
    db_session.refresh(car)
    assert car.on_site is True
    stay = _stays(client, auth_headers, workshop)[0]
    assert stay["has_plan"] and stay["body_car_id"] == str(car.id)
    assert stay["car_description"] == "Skoda"
    _pass(client, auth_headers, gate_id, "exit_confirmed", "А111АА77", at(14))
    db_session.refresh(car)
    assert car.on_site is False


def test_a_car_that_is_not_in_the_plan_is_an_error_and_nothing_is_created(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    _pass(client, auth_headers, gate_id, "entry_confirmed", "К555КК77", at(9))
    assert db_session.scalars(select(BodyCar)).all() == []  # ничего в плане не создаём
    issue = db_session.scalars(select(BayIssue)).one()
    assert issue.kind == "no_body_plan" and issue.plate == "К555КК77" and issue.resolved_at is None
    assert _stays(client, auth_headers, workshop)[0]["has_plan"] is False


def test_the_error_clears_itself_when_the_plan_card_appears_later(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    _pass(client, auth_headers, gate_id, "entry_confirmed", "К555КК77", at(9))
    car = _car(db_session, workshop, "К555КК77")  # мастер завёл карточку после заезда
    bay_planner.tick(db_session, now=at(9, 5))
    db_session.expire_all()
    assert db_session.scalars(select(BayIssue)).one().resolved_at is not None
    assert db_session.get(BodyCar, car.id).on_site is True
    assert _stays(client, auth_headers, workshop)[0]["has_plan"] is True


def test_a_misread_exit_plate_still_finds_the_car_among_those_inside(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    for plate in ("А111АА77", "В222ВВ77"):
        _car(db_session, workshop, plate)
        _pass(client, auth_headers, gate_id, "entry_confirmed", plate, at(9))
    _pass(client, auth_headers, gate_id, "exit_confirmed", "В222ВС77", at(15), confidence=0.6)
    assert [s["plate"] for s in _stays(client, auth_headers, workshop)] == ["А111АА77"]


def test_an_exit_of_a_car_that_is_not_inside_is_an_error(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    _pass(client, auth_headers, gate_id, "exit_confirmed", "Х999ХХ77", at(15))
    issue = db_session.scalars(select(BayIssue)).one()
    assert issue.kind == "exit_without_entry"
    assert _stays(client, auth_headers, workshop) == []


def test_a_car_may_leave_and_come_back_all_stays_share_one_plan_card(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    car = _car(db_session, workshop, "А111АА77")
    _pass(client, auth_headers, gate_id, "entry_confirmed", "А111АА77", at(9))
    _pass(client, auth_headers, gate_id, "exit_confirmed", "А111АА77", at(11))
    db_session.refresh(car)
    assert car.on_site is False
    _pass(client, auth_headers, gate_id, "entry_confirmed", "А111АА77", at(16))
    db_session.refresh(car)
    assert car.on_site is True
    stays = db_session.scalars(select(GateStay).order_by(GateStay.entered_at)).all()
    assert len(stays) == 2 and {s.body_car_id for s in stays} == {car.id}
    assert len(_stays(client, auth_headers, workshop, status="all")) == 2


def test_a_second_read_of_the_same_entry_within_two_minutes_is_not_a_new_stay(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    _car(db_session, workshop, "А111АА77")
    _pass(client, auth_headers, gate_id, "entry_confirmed", "А111АА77", at(9, 0, 0))
    event = _pass(client, auth_headers, gate_id, "entry_confirmed", "А111АА77", at(9, 1, 0))
    assert "не учтён" in event["note"]
    assert len(db_session.scalars(select(GateStay)).all()) == 1


def test_an_entry_of_a_car_already_inside_closes_the_missed_exit_for_review(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    _car(db_session, workshop, "А111АА77")
    _pass(client, auth_headers, gate_id, "entry_confirmed", "А111АА77", at(9))
    _pass(client, auth_headers, gate_id, "entry_confirmed", "А111АА77", at(13))  # выезд не увидели
    stays = db_session.scalars(select(GateStay).order_by(GateStay.entered_at)).all()
    assert len(stays) == 2
    assert stays[0].exited_at is not None and stays[0].review_status == "needs_review"
    assert stays[1].exited_at is None


def test_manual_entry_without_a_plate_and_manual_exit(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    response = client.post(
        "/api/v1/bays/gate/stays",
        json={
            "bay_id": gate_id,
            "label": "Белый Рио без номеров",
            "entered_at": at(10).isoformat(),
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    stay = response.json()
    assert stay["plate"] is None and stay["source"] == "manual"
    assert stay["label"] == "Белый Рио без номеров"
    assert len(_stays(client, auth_headers, workshop)) == 1
    done = client.post(
        f"/api/v1/bays/gate/stays/{stay['id']}/exit",
        json={"exited_at": at(18).isoformat()},
        headers=auth_headers,
    )
    assert done.status_code == 200 and done.json()["exited_at"] is not None
    assert _stays(client, auth_headers, workshop) == []
    again = client.post(f"/api/v1/bays/gate/stays/{stay['id']}/exit", json={}, headers=auth_headers)
    assert again.status_code == 422


def test_correcting_the_plate_finds_the_plan_card_and_clears_the_error(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    car = _car(db_session, workshop, "А111АА77")
    _pass(client, auth_headers, gate_id, "entry_confirmed", "Н000НН99", at(9))  # прочитано криво
    stay = _stays(client, auth_headers, workshop)[0]
    assert stay["has_plan"] is False
    fixed = client.patch(
        f"/api/v1/bays/gate/stays/{stay['id']}", json={"plate": "А111АА77"}, headers=auth_headers
    )
    assert fixed.status_code == 200 and fixed.json()["has_plan"] is True
    db_session.expire_all()
    assert db_session.get(BodyCar, car.id).on_site is True
    assert db_session.scalars(select(BayIssue)).one().resolved_at is not None


def test_the_work_order_number_comes_from_the_plan_cards_order(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    order = WorkOrder(
        external_number="ЭП-77",
        document_date=datetime(2026, 11, 1, tzinfo=UTC),
        amount=0,
        vehicle_description="Skoda № А111АА77 VIN X",
        customer_name="Иванов",
    )
    db_session.add(order)
    db_session.commit()
    _car(db_session, workshop, "А111АА77", work_order_id=order.id)
    _pass(client, auth_headers, gate_id, "entry_confirmed", "А111АА77", at(9))
    stay = _stays(client, auth_headers, workshop)[0]
    assert stay["work_order_number"] == "ЭП-77"
    assert stay["client_name"] == "Иванов"


def test_a_gate_stay_is_never_closed_automatically_when_the_node_is_silent(
    client, auth_headers, gate_id, workshop, db_session
) -> None:
    _car(db_session, workshop, "А111АА77")
    _pass(client, auth_headers, gate_id, "entry_confirmed", "А111АА77", at(9))
    bay_planner.tick(db_session, now=at(9, day=5))  # трое суток без связи: машина остаётся
    assert len(_stays(client, auth_headers, workshop)) == 1
    response = client.post(
        f"/api/v1/bays/{uuid.uuid4()}/events",
        json={"event_type": "entry_confirmed", "plate": "А111АА77"},
        headers=auth_headers,
    )
    assert response.status_code == 404
