"""Видеоконтроль <-> планировщик: перевод записи в «В работе», автосоздание, продление,
«Готова» после выезда, наложение записей и лист «Ошибки»."""

import uuid
from datetime import UTC, date, datetime, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bay import Bay, BayIssue, BayOccupancy, CameraStatus
from app.models.department import Department
from app.models.slesarka_status import SlesarkaStatus
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop
from app.models.workshop_job import WorkshopJob
from app.services import bay_planner
from app.services.settings_service import get_app_settings

DAY = date(2026, 11, 2)  # понедельник
# Москва = UTC+3: 10:00 по цеху = 07:00 UTC
PLAN_URL = "/api/v1/planner"


def moment(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, 2, hour - 3, minute, second, tzinfo=UTC)


@pytest.fixture()
def workshop(db_session: Session) -> Workshop:
    department = Department(name="Каховка")
    db_session.add(department)
    db_session.flush()
    ws = Workshop(
        department_id=department.id,
        workshop_type="Слесарный",
        posts_count=3,
        start_time=time(8, 0),
        end_time=time(20, 0),
        working_days=[0, 1, 2, 3, 4],
    )
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture()
def statuses(db_session: Session) -> dict[str, SlesarkaStatus]:
    rows = {
        name: SlesarkaStatus(name=name, color="#123456")
        for name in ("Запись", "В работе", "Готова", "Отмена")
    }
    db_session.add_all(rows.values())
    db_session.commit()
    return rows


@pytest.fixture()
def bay_id(client: TestClient, auth_headers: dict, workshop: Workshop) -> str:
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    response = client.get(f"/api/v1/bays?workshop_id={workshop.id}", headers=auth_headers)
    bays = response.json()["bays"]
    return bays[1]["id"]  # «Бокс 2» = пост 2


def _event(client, headers, bay, kind, plate=None, at=None):
    body = {"event_type": kind, "plate": plate}
    if at:
        body["occurred_at"] = at.isoformat()
    response = client.post(f"/api/v1/bays/{bay}/events", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _job(db, workshop, status, start, end, plate=None, post=2, order=None) -> WorkshopJob:
    job = WorkshopJob(
        workshop_id=workshop.id,
        job_date=DAY,
        post_number=post,
        start_time=start,
        end_time=end,
        plate=plate,
        status_id=status.id,
        work_order_id=order.id if order else None,
    )
    db.add(job)
    db.commit()
    return job


def _order(db, number="ЗН-1", car="Skoda № А612СМ777 VIN X") -> WorkOrder:
    order = WorkOrder(
        external_number=number,
        document_date=datetime(2026, 11, 1, tzinfo=UTC),
        amount=0,
        vehicle_description=car,
        customer_name="Иванов",
    )
    db.add(order)
    db.commit()
    return order


def _jobs(db: Session, workshop: Workshop) -> list[WorkshopJob]:
    db.expire_all()
    return list(
        db.scalars(
            select(WorkshopJob)
            .where(WorkshopJob.workshop_id == workshop.id)
            .order_by(WorkshopJob.start_time)
        )
    )


def test_entry_moves_the_planned_job_to_work_by_the_first_six_characters(
    client, auth_headers, db_session, workshop, statuses, bay_id
) -> None:
    order = _order(db_session)
    # в плане номер без региона
    job = _job(db_session, workshop, statuses["Запись"], time(10), time(11), "А612СМ", order=order)

    event = _event(client, auth_headers, bay_id, "entry_confirmed", "А612СМ777", moment(10, 5))

    db_session.expire_all()
    job = db_session.get(WorkshopJob, job.id)
    assert job.status_id == statuses["В работе"].id
    assert len(_jobs(db_session, workshop)) == 1  # новую не создавали
    assert event["plate"] == "А612СМ777"
    assert db_session.scalars(select(BayIssue)).all() == []  # заказ-наряд есть


def test_a_car_that_came_early_still_finds_a_later_plan_of_the_day(
    client, auth_headers, db_session, workshop, statuses, bay_id
) -> None:
    order = _order(db_session)
    job = _job(db_session, workshop, statuses["Запись"], time(15), time(16), "А612СМ", order=order)

    _event(client, auth_headers, bay_id, "entry_confirmed", "А612СМ777", moment(10, 0))

    db_session.expire_all()
    assert db_session.get(WorkshopJob, job.id).status_id == statuses["В работе"].id
    assert len(_jobs(db_session, workshop)) == 1


def _control_posts(db, enabled: bool) -> None:
    settings = get_app_settings(db)
    settings.control_posts_enabled = enabled
    db.commit()


def test_with_posts_not_controlled_the_plan_is_found_on_any_post_and_started_there(
    client, auth_headers, db_session, workshop, statuses, bay_id
) -> None:
    order = _order(db_session)
    other_post = _job(
        db_session, workshop, statuses["Запись"], time(10), time(11), "А612СМ", post=1, order=order
    )

    _event(client, auth_headers, bay_id, "entry_confirmed", "А612СМ777", moment(10, 5))

    db_session.expire_all()
    job = db_session.get(WorkshopJob, other_post.id)
    assert (job.post_number, job.status_id) == (1, statuses["В работе"].id)  # осталась на посту 1
    assert len(_jobs(db_session, workshop)) == 1  # на посту камеры ничего не создано


def test_other_post_or_other_plate_is_not_matched_when_posts_are_controlled(
    client, auth_headers, db_session, workshop, statuses, bay_id
) -> None:
    _control_posts(db_session, True)
    order = _order(db_session)
    other_post = _job(
        db_session, workshop, statuses["Запись"], time(10), time(11), "А612СМ", post=1, order=order
    )
    other_plate = _job(db_session, workshop, statuses["Запись"], time(10), time(11), "В999ВВ")

    _event(client, auth_headers, bay_id, "entry_confirmed", "А612СМ777", moment(10, 5))

    db_session.expire_all()
    assert db_session.get(WorkshopJob, other_post.id).status_id == statuses["Запись"].id
    assert db_session.get(WorkshopJob, other_plate.id).status_id == statuses["Запись"].id
    created = [
        j for j in _jobs(db_session, workshop) if j.post_number == 2 and j.plate == "А612СМ777"
    ]
    assert len(created) == 1


def test_no_plan_creates_a_thirty_minute_job_linked_to_the_work_order(
    client, auth_headers, db_session, workshop, statuses, bay_id
) -> None:
    order = _order(db_session)

    _event(client, auth_headers, bay_id, "entry_confirmed", "А612СМ777", moment(10, 12))

    [job] = _jobs(db_session, workshop)
    assert (job.post_number, job.start_time, job.end_time) == (2, time(10, 12), time(10, 42))
    assert job.status_id == statuses["В работе"].id
    assert job.work_order_id == order.id
    assert job.client_name == "Иванов"
    assert db_session.scalars(select(BayIssue)).all() == []


def test_the_job_is_extended_while_the_car_stays_and_done_after_exit(
    client, auth_headers, db_session, workshop, statuses, bay_id
) -> None:
    _order(db_session)
    _event(client, auth_headers, bay_id, "entry_confirmed", "А612СМ777", moment(10, 0))
    [job] = _jobs(db_session, workshop)
    assert job.end_time == time(10, 30)

    bay_planner.tick(db_session, moment(10, 20))  # ещё в пределах записи
    assert _jobs(db_session, workshop)[0].end_time == time(10, 30)

    bay_planner.tick(db_session, moment(10, 31))  # вышла за конец записи
    assert _jobs(db_session, workshop)[0].end_time == time(11, 0)

    bay_planner.tick(db_session, moment(11, 45, 10))
    assert _jobs(db_session, workshop)[0].end_time == time(12, 0)

    _event(client, auth_headers, bay_id, "exit_confirmed", at=moment(11, 50))
    [job] = _jobs(db_session, workshop)
    assert job.status_id == statuses["Готова"].id

    bay_planner.tick(db_session, moment(13, 0))  # машины нет - не продлеваем
    assert _jobs(db_session, workshop)[0].end_time == time(12, 0)


def test_extension_stops_at_the_end_of_the_working_day(
    client, auth_headers, db_session, workshop, statuses, bay_id
) -> None:
    _order(db_session)
    _event(client, auth_headers, bay_id, "entry_confirmed", "А612СМ777", moment(19, 40))
    bay_planner.tick(db_session, moment(20, 5))
    [job] = _jobs(db_session, workshop)
    assert job.end_time == time(20, 0)


def test_two_jobs_may_overlap_on_one_post(
    client, auth_headers, db_session, workshop, statuses
) -> None:
    payload = {
        "job_date": DAY.isoformat(),
        "post_number": 1,
        "start_time": "10:00:00",
        "end_time": "11:00:00",
    }
    for _ in range(2):
        response = client.post(
            f"{PLAN_URL}/workshops/{workshop.id}/jobs", json=payload, headers=auth_headers
        )
        assert response.status_code == 201


def test_a_planned_car_that_did_not_come_does_not_block_the_one_that_did(
    client, auth_headers, db_session, workshop, statuses, bay_id
) -> None:
    order = _order(db_session)
    planned = _job(db_session, workshop, statuses["Запись"], time(10), time(11), "В999ВВ")

    _event(client, auth_headers, bay_id, "entry_confirmed", "А612СМ777", moment(10, 5))

    jobs = _jobs(db_session, workshop)
    assert len(jobs) == 2  # плановая осталась, для приехавшей создана своя
    db_session.expire_all()
    assert db_session.get(WorkshopJob, planned.id).status_id == statuses["Запись"].id
    assert any(j.work_order_id == order.id for j in jobs)


def test_a_car_without_a_work_order_creates_an_issue_that_can_be_resolved(
    client, auth_headers, db_session, workshop, statuses, bay_id
) -> None:
    _event(client, auth_headers, bay_id, "entry_confirmed", "К555ММ77", moment(10, 0))

    summary = client.get("/api/v1/bays/issues/summary", headers=auth_headers).json()
    assert summary == {"open_count": 1}
    [issue] = client.get("/api/v1/bays/issues?status=open", headers=auth_headers).json()["issues"]
    assert issue["plate"] == "К555ММ77"
    assert issue["bay_name"] == "Бокс 2"
    assert "заказ-наряда" in issue["message"]

    done = client.post(
        f"/api/v1/bays/issues/{issue['id']}/resolve",
        json={"note": "оформили"},
        headers={**auth_headers, "X-Actor-Name": "%D0%98%D0%B2%D0%B0%D0%BD"},
    )
    assert done.status_code == 200
    assert client.get("/api/v1/bays/issues/summary", headers=auth_headers).json() == {
        "open_count": 0
    }
    [closed] = client.get("/api/v1/bays/issues?status=resolved", headers=auth_headers).json()[
        "issues"
    ]
    assert (closed["resolution"], closed["resolved_by"], closed["resolution_note"]) == (
        "manual",
        "Иван",
        "оформили",
    )


def test_the_issue_closes_itself_when_the_work_order_appears(
    client, auth_headers, db_session, workshop, statuses, bay_id
) -> None:
    _event(client, auth_headers, bay_id, "entry_confirmed", "А612СМ777", moment(10, 0))
    assert client.get("/api/v1/bays/issues/summary", headers=auth_headers).json()["open_count"] == 1

    order = _order(db_session)  # заказ-наряд оформили позже
    extended, resolved = bay_planner.tick(db_session, moment(10, 10))

    assert resolved == 1
    assert client.get("/api/v1/bays/issues/summary", headers=auth_headers).json()["open_count"] == 0
    [issue] = client.get("/api/v1/bays/issues", headers=auth_headers).json()["issues"]
    assert issue["resolution"] == "auto"
    [job] = _jobs(db_session, workshop)
    assert job.work_order_id == order.id  # заказ-наряд подтянулся и в запись плана


def test_work_order_linked_in_the_planner_closes_the_issue(
    client, auth_headers, db_session, workshop, statuses, bay_id
) -> None:
    _event(client, auth_headers, bay_id, "entry_confirmed", "К555ММ77", moment(10, 0))
    [job] = _jobs(db_session, workshop)
    other = _order(db_session, "ЗН-9", "Audi VIN Y")  # номер в заказе другой

    job.work_order_id = other.id  # управляющий привязал заказ-наряд к записи вручную
    db_session.commit()
    _, resolved = bay_planner.tick(db_session, moment(10, 5))

    assert resolved == 1
    assert db_session.scalars(select(BayIssue).where(BayIssue.resolved_at.is_(None))).all() == []


def test_an_issue_is_not_duplicated_and_unknown_issue_is_404(
    client, auth_headers, db_session, workshop, statuses, bay_id
) -> None:
    _event(client, auth_headers, bay_id, "entry_confirmed", "К555ММ77", moment(10, 0))
    bay_planner.tick(db_session, moment(10, 5))
    assert len(db_session.scalars(select(BayIssue)).all()) == 1
    missing = client.post(
        f"/api/v1/bays/issues/{uuid.uuid4()}/resolve", json={}, headers=auth_headers
    )
    assert missing.status_code == 404


def test_body_workshop_gets_issues_but_no_planner_records(
    client, auth_headers, db_session, statuses
) -> None:
    department = Department(name="Солнцево")
    db_session.add(department)
    db_session.flush()
    body = Workshop(
        department_id=department.id,
        workshop_type="Кузовной",
        posts_count=2,
        start_time=time(8),
        end_time=time(20),
        working_days=[0, 1, 2, 3, 4],
    )
    db_session.add(body)
    db_session.commit()
    client.post(f"/api/v1/bays/defaults?workshop_id={body.id}", headers=auth_headers)
    bays = client.get(f"/api/v1/bays?workshop_id={body.id}", headers=auth_headers).json()["bays"]

    _event(client, auth_headers, bays[0]["id"], "entry_confirmed", "К555ММ77", moment(10, 0))

    assert db_session.scalars(select(WorkshopJob)).all() == []
    assert len(db_session.scalars(select(BayIssue)).all()) == 1
    assert db_session.scalars(select(BayOccupancy)).first().workshop_job_id is None


def _event_with_confidence(client, headers, bay, kind, plate, confidence, at):
    body = {
        "event_type": kind,
        "plate": plate,
        "ocr_confidence": confidence,
        "occurred_at": at.isoformat(),
    }
    response = client.post(f"/api/v1/bays/{bay}/events", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_low_confidence_entry_does_not_create_a_planner_record(
    client, auth_headers, bay_id, workshop, statuses, db_session
) -> None:
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "Е479АР77", 0.25, moment(15, 46)
    )
    assert db_session.scalars(select(WorkshopJob)).all() == []

    _event_with_confidence(
        client, auth_headers, bay_id, "exit_confirmed", "Е479АР77", 0.25, moment(16, 30)
    )
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "Е747АО997", 0.93, moment(17, 0)
    )
    jobs = db_session.scalars(select(WorkshopJob)).all()
    assert len(jobs) == 1 and jobs[0].plate == "Е747АО997"


def test_a_re_entry_within_two_minutes_cancels_the_false_exit(
    client, auth_headers, bay_id, workshop, statuses, db_session
) -> None:
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "Т652АК977", 0.93, moment(12, 0)
    )
    job = db_session.scalars(select(WorkshopJob)).one()
    _event_with_confidence(
        client, auth_headers, bay_id, "exit_confirmed", "Т652АК977", 0.93, moment(15, 46, 7)
    )
    db_session.expire_all()
    assert db_session.get(WorkshopJob, job.id).status_id == statuses["Готова"].id

    # Через 14 секунд «въезд» другого (кривого) номера: это та же машина, выезд был ложным.
    quick = _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "А697ТТ77", 0.9, moment(15, 46, 21)
    )
    assert "не учтён" in quick["note"]
    db_session.expire_all()
    intervals = db_session.scalars(select(BayOccupancy)).all()
    assert len(intervals) == 1 and intervals[0].ended_at is None  # бокс снова занят
    assert db_session.get(WorkshopJob, job.id).status_id == statuses["В работе"].id
    assert len(db_session.scalars(select(WorkshopJob)).all()) == 1

    # Настоящий выезд закрывает тот же заезд; следующий въезд через три минуты считается.
    _event_with_confidence(
        client, auth_headers, bay_id, "exit_confirmed", "Т652АК977", 0.93, moment(15, 47, 15)
    )
    db_session.expire_all()
    assert db_session.scalars(select(BayOccupancy)).one().ended_at is not None
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "Х123ХХ77", 0.9, moment(15, 51)
    )
    assert len(db_session.scalars(select(BayOccupancy)).all()) == 2


def test_an_entry_while_the_bay_is_occupied_is_ignored_unless_it_is_a_confident_new_car(
    client, auth_headers, bay_id, workshop, statuses, db_session
) -> None:
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "Т652АК977", 0.93, moment(12, 0)
    )
    # Кривое чтение (ниже 70 %) и тот же номер при занятом боксе - не новая машина.
    low = _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "А697ТТ77", 0.45, moment(12, 5)
    )
    same = _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "Т652АК977", 0.95, moment(12, 6)
    )
    assert "без выезда" in low["note"] and "без выезда" in same["note"]
    assert len(db_session.scalars(select(BayOccupancy)).all()) == 1

    # Уверенный другой номер: выезд, видимо, пропущен - считаем, но на проверку.
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "Х123ХХ77", 0.95, moment(12, 10)
    )
    assert len(db_session.scalars(select(BayOccupancy)).all()) == 2


def _node_seen(db, code, at):
    db.add(CameraStatus(camera_code=code, seen_at=at, camera_ok=True, camera_ok_since=at))
    db.commit()


def test_an_occupancy_is_closed_when_the_node_has_been_offline_for_over_three_hours(
    client, auth_headers, bay_id, workshop, statuses, db_session
) -> None:
    db_session.get(Bay, uuid.UUID(bay_id)).camera_code = "cam2"
    db_session.commit()
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "Т652АК977", 0.93, moment(18, 19)
    )
    _node_seen(db_session, "cam2", moment(18, 52))

    # Через два с половиной часа узла нет, но это ещё не повод закрывать.
    bay_planner.tick(db_session, now=moment(21, 20))
    assert db_session.scalars(select(BayOccupancy)).one().ended_at is None

    # Утром узел так и не отвечал: заезд закрывается временем последнего сигнала узла.
    bay_planner.tick(db_session, now=moment(21, 0).replace(day=3, hour=6))
    interval = db_session.scalars(select(BayOccupancy)).one()
    assert interval.ended_at is not None
    assert interval.ended_at.replace(tzinfo=UTC) == moment(18, 52)
    job = db_session.scalars(select(WorkshopJob)).one()
    assert job.status_id == statuses["Готова"].id


def test_a_fresh_node_or_a_manual_occupancy_is_never_closed_automatically(
    client, auth_headers, bay_id, workshop, statuses, db_session
) -> None:
    db_session.get(Bay, uuid.UUID(bay_id)).camera_code = "cam2"
    db_session.commit()
    _node_seen(db_session, "cam2", moment(18, 52))
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "Т652АК977", 0.93, moment(18, 19)
    )
    bay_planner.tick(db_session, now=moment(20, 30))  # узел был 1 ч 38 мин назад: ждём
    assert db_session.scalars(select(BayOccupancy)).one().ended_at is None

    # Заезд, введённый оператором, при выключенном узле остаётся.
    response = client.post(
        f"/api/v1/bays/{bay_id}/events",
        json={
            "event_type": "exit_confirmed",
            "plate": "Т652АК977",
            "source": "manual",
            "occurred_at": moment(19, 31).isoformat(),
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    client.post(
        f"/api/v1/bays/{bay_id}/events",
        json={
            "event_type": "entry_confirmed",
            "plate": "О805КТ977",
            "source": "manual",
            "occurred_at": moment(20, 0).isoformat(),
        },
        headers=auth_headers,
    )
    bay_planner.tick(db_session, now=moment(23, 0))
    manual = db_session.scalars(select(BayOccupancy).where(BayOccupancy.plate == "О805КТ977")).one()
    assert manual.ended_at is None


def test_a_quick_entry_of_a_different_known_car_is_a_new_car_not_a_return(
    client, auth_headers, bay_id, workshop, statuses, db_session
) -> None:
    """2026-11-18: Audi уехала, через минуту заехал Ford с другим заказ-нарядом. Выезд Audi
    нельзя отменять, а Ford - это новый заезд."""
    _order(db_session, "ЗН-AUDI", "Audi № К279КО777 VIN A")
    _order(db_session, "ЗН-FORD", "Ford № К679ОО777 VIN B")
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "К279КО777", 0.97, moment(13, 5)
    )
    _event_with_confidence(
        client, auth_headers, bay_id, "exit_confirmed", "К279КО777", 0.97, moment(14, 20, 57)
    )
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "К679ОО777", 0.76, moment(14, 21, 53)
    )
    db_session.expire_all()
    intervals = db_session.scalars(
        select(BayOccupancy).order_by(BayOccupancy.started_at)
    ).all()
    assert len(intervals) == 2
    assert intervals[0].ended_at is not None  # выезд Audi остался в силе
    assert intervals[1].ended_at is None and intervals[1].plate.startswith("К679ОО")


def test_a_confidently_read_different_plate_is_a_new_car_even_without_a_work_order(
    client, auth_headers, bay_id, workshop, statuses, db_session
) -> None:
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "К279КО777", 0.97, moment(13, 5)
    )
    _event_with_confidence(
        client, auth_headers, bay_id, "exit_confirmed", "К279КО777", 0.97, moment(14, 20)
    )
    body = {
        "event_type": "entry_confirmed",
        "plate": "М111ММ77",
        "ocr_confidence": 0.9,
        "occurred_at": moment(14, 21).isoformat(),
        "note": "прочитано: М111ММ77 (первые 6 символов: 100%, кадров: 10)",
    }
    assert client.post(f"/api/v1/bays/{bay_id}/events", json=body, headers=auth_headers).status_code == 201
    db_session.expire_all()
    intervals = db_session.scalars(select(BayOccupancy).order_by(BayOccupancy.started_at)).all()
    assert len(intervals) == 2 and intervals[0].ended_at is not None


def test_the_bay_card_does_not_show_a_cancelled_exit(
    client, auth_headers, bay_id, workshop, statuses, db_session
) -> None:
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "Т652АК977", 0.93, moment(12, 0)
    )
    _event_with_confidence(
        client, auth_headers, bay_id, "exit_confirmed", "Т652АК977", 0.93, moment(15, 46, 7)
    )
    # Через 14 секунд «въезд» кривого номера: выезд ложный и отменяется.
    _event_with_confidence(
        client, auth_headers, bay_id, "entry_confirmed", "А697ТТ77", 0.9, moment(15, 46, 21)
    )
    bays = client.get(f"/api/v1/bays?workshop_id={workshop.id}", headers=auth_headers).json()
    card = next(b for b in bays["bays"] if b["id"] == bay_id)
    assert card["last_exit"] is None  # единственный выезд отменён
    assert card["last_entry"]["plate"] == "Т652АК977"
