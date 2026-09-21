"""Tests for the Planner (Слесарный/Кузовной цех) - see
app/services/planner_service.py, app/api/v1/endpoints/planner.py."""

from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import quote

import pytest
from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.slesarka_status import SlesarkaStatus
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop

PLANNER_URL = "/api/v1/planner"


@pytest.fixture()
def mechanical_workshop(db_session: Session) -> Workshop:
    department = Department(name="Каховка")
    db_session.add(department)
    db_session.flush()
    workshop = Workshop(
        department_id=department.id,
        workshop_type="Слесарный",
        posts_count=3,
        start_time="07:00:00",
        end_time="22:00:00",
        working_days=[0, 1, 2, 3, 4, 5],
    )
    db_session.add(workshop)
    db_session.commit()
    db_session.refresh(workshop)
    return workshop


@pytest.fixture()
def body_workshop(db_session: Session) -> Workshop:
    department = Department(name="Солнцево")
    db_session.add(department)
    db_session.flush()
    workshop = Workshop(
        department_id=department.id,
        workshop_type="Кузовной",
        posts_count=1,
        start_time="07:00:00",
        end_time="22:00:00",
        working_days=[0, 1, 2, 3, 4, 5, 6],
    )
    db_session.add(workshop)
    db_session.commit()
    db_session.refresh(workshop)
    return workshop


@pytest.fixture()
def slesarka_status(db_session: Session) -> SlesarkaStatus:
    status = SlesarkaStatus(name="Запись", color="#5b6b82")
    db_session.add(status)
    db_session.commit()
    db_session.refresh(status)
    return status


@pytest.fixture()
def sample_work_order(db_session: Session) -> WorkOrder:
    wo = WorkOrder(
        external_number="СЛ00000371",
        source_system="alpha-auto",
        document_date=datetime(2026, 9, 20, tzinfo=UTC),
        customer_name="Иванов Иван",
        vehicle_description="Toyota Camry",
        vin="WVWZZZ1JZXW000001",
        amount=Decimal("14800.00"),
    )
    db_session.add(wo)
    db_session.commit()
    db_session.refresh(wo)
    return wo


def _actor_header(name: str) -> dict:
    # Header VALUES are ASCII/Latin-1-only (Fetch API, httpx) - the real
    # proxy percent-encodes Cyrillic actor names, see
    # app/api/v1/endpoints/planner.py's actor() dependency.
    return {"X-Actor-Name": quote(name)}


def _job_payload(**overrides) -> dict:
    payload = {
        "work_order_id": None,
        "car_description": "Toyota Camry",
        "vin": None,
        "plate": "А123ВС797",
        "client_name": "Иванов Иван",
        "work_description": "ТО-60",
        "job_date": "2026-09-21",
        "post_number": 1,
        "start_time": "09:00:00",
        "end_time": "11:00:00",
        "norm_hours": None,
        "status_id": None,
    }
    payload.update(overrides)
    return payload


# ---- ЗН autocomplete --------------------------------------------------------


def test_search_work_orders_matches_number_and_vehicle(
    client, auth_headers, sample_work_order
) -> None:
    by_number = client.get(
        f"{PLANNER_URL}/work-orders/search", params={"q": "СЛ0000037"}, headers=auth_headers
    )
    assert by_number.status_code == 200
    assert [w["external_number"] for w in by_number.json()] == ["СЛ00000371"]

    by_vehicle = client.get(
        f"{PLANNER_URL}/work-orders/search", params={"q": "Camry"}, headers=auth_headers
    )
    assert [w["external_number"] for w in by_vehicle.json()] == ["СЛ00000371"]

    no_match = client.get(
        f"{PLANNER_URL}/work-orders/search", params={"q": "qqqqq"}, headers=auth_headers
    )
    assert no_match.json() == []


# ---- Слесарный --------------------------------------------------------------


def test_create_and_list_workshop_job(
    client, auth_headers, mechanical_workshop, sample_work_order
) -> None:
    response = client.post(
        f"{PLANNER_URL}/workshops/{mechanical_workshop.id}/jobs",
        headers={**auth_headers, **_actor_header("Тест Тестов")},
        json=_job_payload(work_order_id=str(sample_work_order.id)),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["work_order_number"] == "СЛ00000371"
    assert body["amount"] == "14800.00"

    listed = client.get(
        f"{PLANNER_URL}/workshops/{mechanical_workshop.id}/jobs",
        params={"date_from": "2026-09-21", "date_to": "2026-09-21"},
        headers=auth_headers,
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_workshop_job_rejects_overlapping_slot(client, auth_headers, mechanical_workshop) -> None:
    first = client.post(
        f"{PLANNER_URL}/workshops/{mechanical_workshop.id}/jobs",
        headers=auth_headers,
        json=_job_payload(),
    )
    assert first.status_code == 201

    overlapping = client.post(
        f"{PLANNER_URL}/workshops/{mechanical_workshop.id}/jobs",
        headers=auth_headers,
        json=_job_payload(start_time="10:00:00", end_time="12:00:00"),
    )
    assert overlapping.status_code == 422

    adjacent = client.post(
        f"{PLANNER_URL}/workshops/{mechanical_workshop.id}/jobs",
        headers=auth_headers,
        json=_job_payload(start_time="11:00:00", end_time="12:00:00"),
    )
    assert adjacent.status_code == 201

    different_post = client.post(
        f"{PLANNER_URL}/workshops/{mechanical_workshop.id}/jobs",
        headers=auth_headers,
        json=_job_payload(post_number=2),
    )
    assert different_post.status_code == 201


def test_workshop_job_rejects_outside_working_hours(
    client, auth_headers, mechanical_workshop
) -> None:
    response = client.post(
        f"{PLANNER_URL}/workshops/{mechanical_workshop.id}/jobs",
        headers=auth_headers,
        json=_job_payload(start_time="06:00:00", end_time="08:00:00"),
    )
    assert response.status_code == 422


def test_workshop_job_rejects_non_working_day(client, auth_headers, mechanical_workshop) -> None:
    # 2026-09-27 is a Sunday (weekday 6), not in working_days=[0..5].
    response = client.post(
        f"{PLANNER_URL}/workshops/{mechanical_workshop.id}/jobs",
        headers=auth_headers,
        json=_job_payload(job_date="2026-09-27"),
    )
    assert response.status_code == 422


def test_update_and_delete_workshop_job(
    client, auth_headers, mechanical_workshop, slesarka_status
) -> None:
    created = client.post(
        f"{PLANNER_URL}/workshops/{mechanical_workshop.id}/jobs",
        headers=auth_headers,
        json=_job_payload(),
    )
    job_id = created.json()["id"]

    updated = client.put(
        f"{PLANNER_URL}/jobs/{job_id}",
        headers=auth_headers,
        json=_job_payload(post_number=2, status_id=str(slesarka_status.id)),
    )
    assert updated.status_code == 200
    assert updated.json()["post_number"] == 2
    assert updated.json()["status_name"] == "Запись"

    deleted = client.delete(f"{PLANNER_URL}/jobs/{job_id}", headers=auth_headers)
    assert deleted.status_code == 204

    listed = client.get(
        f"{PLANNER_URL}/workshops/{mechanical_workshop.id}/jobs",
        params={"date_from": "2026-09-21", "date_to": "2026-09-21"},
        headers=auth_headers,
    )
    assert listed.json() == []


def test_workshop_job_audit_log_records_create_update_delete(
    client, auth_headers, mechanical_workshop, db_session: Session
) -> None:
    created = client.post(
        f"{PLANNER_URL}/workshops/{mechanical_workshop.id}/jobs",
        headers={**auth_headers, **_actor_header("Мастер Иванов")},
        json=_job_payload(),
    )
    job_id = created.json()["id"]

    client.put(
        f"{PLANNER_URL}/jobs/{job_id}",
        headers={**auth_headers, **_actor_header("Мастер Иванов")},
        json=_job_payload(post_number=3),
    )
    client.delete(
        f"{PLANNER_URL}/jobs/{job_id}", headers={**auth_headers, **_actor_header("Мастер Иванов")}
    )

    log = client.get("/api/v1/settings/audit-log", headers=auth_headers).json()
    actions = [entry["action"] for entry in log if entry["entity_id"] == job_id]
    assert actions == ["delete", "update", "create"]  # newest first
    assert all(
        entry["actor_name"] == "Мастер Иванов" for entry in log if entry["entity_id"] == job_id
    )


# ---- Кузовной -----------------------------------------------------------


def _car_payload(**overrides) -> dict:
    payload = {
        "work_order_id": None,
        "car_description": "Octavia A7",
        "vin": None,
        "plate": None,
        "client_name": "Петров П.",
        "work_description": "Пороги, капот",
        "status": "К приёмке",
        "stages": [
            {
                "stage_name": "Приёмка",
                "note": None,
                "start_date": "2026-09-21",
                "end_date": "2026-09-21",
            },
        ],
    }
    payload.update(overrides)
    return payload


def test_create_and_list_body_car(client, auth_headers, body_workshop) -> None:
    response = client.post(
        f"{PLANNER_URL}/workshops/{body_workshop.id}/cars",
        headers=auth_headers,
        json=_car_payload(),
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["stages"]) == 1
    assert body["color"]  # assigned automatically

    listed = client.get(f"{PLANNER_URL}/workshops/{body_workshop.id}/cars", headers=auth_headers)
    assert len(listed.json()) == 1


def test_body_car_colors_rotate_round_robin(client, auth_headers, body_workshop) -> None:
    colors = []
    for _ in range(3):
        response = client.post(
            f"{PLANNER_URL}/workshops/{body_workshop.id}/cars",
            headers=auth_headers,
            json=_car_payload(),
        )
        colors.append(response.json()["color"])
    assert len(set(colors)) == 3  # three different cars, three different colors


def test_body_car_rejects_backwards_stage_dates(client, auth_headers, body_workshop) -> None:
    response = client.post(
        f"{PLANNER_URL}/workshops/{body_workshop.id}/cars",
        headers=auth_headers,
        json=_car_payload(
            stages=[
                {
                    "stage_name": "Приёмка",
                    "note": None,
                    "start_date": "2026-09-22",
                    "end_date": "2026-09-23",
                },
                {
                    "stage_name": "Разбор",
                    "note": None,
                    "start_date": "2026-09-21",
                    "end_date": "2026-09-24",
                },
            ]
        ),
    )
    assert response.status_code == 422


def test_update_body_car_replaces_stages(client, auth_headers, body_workshop) -> None:
    created = client.post(
        f"{PLANNER_URL}/workshops/{body_workshop.id}/cars",
        headers=auth_headers,
        json=_car_payload(),
    )
    car_id = created.json()["id"]

    updated = client.put(
        f"{PLANNER_URL}/cars/{car_id}",
        headers=auth_headers,
        json=_car_payload(
            status="В работе",
            stages=[
                {
                    "stage_name": "Приёмка",
                    "note": None,
                    "start_date": "2026-09-21",
                    "end_date": "2026-09-21",
                },
                {
                    "stage_name": "Жесть",
                    "note": "ремонт",
                    "start_date": "2026-09-22",
                    "end_date": "2026-09-24",
                },
            ],
        ),
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "В работе"
    assert len(updated.json()["stages"]) == 2
    assert updated.json()["stages"][1]["stage_name"] == "Жесть"


def test_delete_body_car(client, auth_headers, body_workshop) -> None:
    created = client.post(
        f"{PLANNER_URL}/workshops/{body_workshop.id}/cars",
        headers=auth_headers,
        json=_car_payload(),
    )
    car_id = created.json()["id"]

    deleted = client.delete(f"{PLANNER_URL}/cars/{car_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert (
        client.get(f"{PLANNER_URL}/workshops/{body_workshop.id}/cars", headers=auth_headers).json()
        == []
    )
