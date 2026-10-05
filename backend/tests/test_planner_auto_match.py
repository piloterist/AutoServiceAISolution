"""Tests for services/planner_service.auto_match_planner_records - see that
function's own docstring for the matching rule (phone or VIN, within a
3-day window after the planner record's own created_at)."""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.body_car import BodyCar
from app.models.department import Department
from app.models.schedule_audit_log import ScheduleAuditLog
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop
from app.models.workshop_job import WorkshopJob
from app.services import planner_service

RECORD_CREATED_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.fixture()
def workshop(db_session: Session) -> Workshop:
    department = Department(name="Каховка")
    db_session.add(department)
    db_session.flush()
    ws = Workshop(
        department_id=department.id,
        workshop_type="Слесарный",
        posts_count=3,
        start_time="07:00:00",
        end_time="22:00:00",
        working_days=[0, 1, 2, 3, 4, 5],
    )
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    return ws


@pytest.fixture()
def body_workshop(db_session: Session) -> Workshop:
    department = Department(name="Солнцево")
    db_session.add(department)
    db_session.flush()
    ws = Workshop(
        department_id=department.id,
        workshop_type="Кузовной",
        posts_count=1,
        start_time="07:00:00",
        end_time="22:00:00",
        working_days=[0, 1, 2, 3, 4, 5, 6],
    )
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    return ws


def _job(
    db_session: Session,
    workshop: Workshop,
    *,
    phone: str | None = None,
    vin: str | None = None,
    car_description: str | None = None,
    client_name: str | None = None,
    created_at: datetime = RECORD_CREATED_AT,
    work_order_id=None,
) -> WorkshopJob:
    job = WorkshopJob(
        workshop_id=workshop.id,
        phone=phone,
        vin=vin,
        car_description=car_description,
        client_name=client_name,
        job_date=created_at.date(),
        post_number=1,
        start_time=time(9, 0),
        end_time=time(10, 0),
        work_order_id=work_order_id,
    )
    db_session.add(job)
    db_session.commit()
    job.created_at = created_at
    db_session.commit()
    db_session.refresh(job)
    return job


def _car(
    db_session: Session,
    workshop: Workshop,
    *,
    phone: str | None = None,
    vin: str | None = None,
    created_at: datetime = RECORD_CREATED_AT,
    work_order_id=None,
) -> BodyCar:
    car = BodyCar(
        workshop_id=workshop.id,
        phone=phone,
        vin=vin,
        color="#ffffff",
        work_order_id=work_order_id,
    )
    db_session.add(car)
    db_session.commit()
    car.created_at = created_at
    db_session.commit()
    db_session.refresh(car)
    return car


def _work_order(
    db_session: Session,
    *,
    phone: str | None = None,
    vin: str | None = None,
    created_at: datetime,
    external_number: str = "СЛ00000500",
    vehicle_description: str = "Toyota Camry",
    customer_name: str = "Иванов Иван",
) -> WorkOrder:
    wo = WorkOrder(
        external_number=external_number,
        source_system="alpha-auto",
        document_date=created_at,
        customer_name=customer_name,
        vehicle_description=vehicle_description,
        vin=vin,
        phone=phone,
        amount=Decimal("10000.00"),
    )
    db_session.add(wo)
    db_session.commit()
    wo.created_at = created_at
    db_session.commit()
    db_session.refresh(wo)
    return wo


def test_matches_by_phone_within_window_and_inherits_fields(
    db_session: Session, workshop: Workshop
) -> None:
    job = _job(db_session, workshop, phone="9261234567")
    wo = _work_order(
        db_session,
        phone="+7 (926) 123-45-67",  # same number, different raw formatting
        created_at=RECORD_CREATED_AT + timedelta(days=1),
    )

    stats = planner_service.auto_match_planner_records(db_session)

    assert stats.processed == 1
    assert stats.matched == 1
    db_session.refresh(job)
    assert job.work_order_id == wo.id
    assert job.car_description == wo.vehicle_description
    assert job.client_name == wo.customer_name


def test_matches_by_vin_when_phone_absent(db_session: Session, body_workshop: Workshop) -> None:
    car = _car(db_session, body_workshop, vin="WVWZZZ1JZXW000001")
    wo = _work_order(
        db_session,
        vin="wvwzzz1jzxw000001",  # same VIN, different case
        created_at=RECORD_CREATED_AT + timedelta(hours=5),
    )

    stats = planner_service.auto_match_planner_records(db_session)

    assert stats.matched == 1
    db_session.refresh(car)
    assert car.work_order_id == wo.id


def test_ignores_work_order_created_before_the_record(
    db_session: Session, workshop: Workshop
) -> None:
    job = _job(db_session, workshop, phone="9261234567")
    _work_order(
        db_session,
        phone="9261234567",
        created_at=RECORD_CREATED_AT - timedelta(hours=1),  # pre-existing, unrelated visit
    )

    stats = planner_service.auto_match_planner_records(db_session)

    assert stats.matched == 0
    db_session.refresh(job)
    assert job.work_order_id is None


def test_ignores_work_order_created_too_late(db_session: Session, workshop: Workshop) -> None:
    job = _job(db_session, workshop, phone="9261234567")
    _work_order(
        db_session,
        phone="9261234567",
        created_at=RECORD_CREATED_AT + timedelta(days=4),  # past the 3-day window
    )

    stats = planner_service.auto_match_planner_records(db_session)

    assert stats.matched == 0
    db_session.refresh(job)
    assert job.work_order_id is None


def test_skips_record_already_linked(db_session: Session, workshop: Workshop) -> None:
    existing_wo = _work_order(db_session, created_at=RECORD_CREATED_AT - timedelta(days=10))
    job = _job(db_session, workshop, phone="9261234567", work_order_id=existing_wo.id)
    _work_order(
        db_session,
        phone="9261234567",
        created_at=RECORD_CREATED_AT + timedelta(hours=1),
        external_number="СЛ00000999",
    )

    stats = planner_service.auto_match_planner_records(db_session)

    assert stats.processed == 0  # never even looked at - already linked
    assert stats.matched == 0
    db_session.refresh(job)
    assert job.work_order_id == existing_wo.id


def test_never_overwrites_a_field_already_typed_by_hand(
    db_session: Session, workshop: Workshop
) -> None:
    job = _job(db_session, workshop, phone="9261234567", car_description="Уже заполнено вручную")
    _work_order(
        db_session,
        phone="9261234567",
        created_at=RECORD_CREATED_AT + timedelta(hours=1),
        vehicle_description="Другое авто из ЗН",
    )

    stats = planner_service.auto_match_planner_records(db_session)

    assert stats.matched == 1
    db_session.refresh(job)
    assert job.work_order_id is not None
    assert job.car_description == "Уже заполнено вручную"


def test_picks_the_earliest_matching_work_order(db_session: Session, workshop: Workshop) -> None:
    job = _job(db_session, workshop, phone="9261234567")
    later = _work_order(
        db_session,
        phone="9261234567",
        created_at=RECORD_CREATED_AT + timedelta(days=2),
        external_number="СЛ00000900",
    )
    earlier = _work_order(
        db_session,
        phone="9261234567",
        created_at=RECORD_CREATED_AT + timedelta(hours=2),
        external_number="СЛ00000901",
    )

    planner_service.auto_match_planner_records(db_session)

    db_session.refresh(job)
    assert job.work_order_id == earlier.id
    assert job.work_order_id != later.id


def test_no_match_when_record_has_neither_phone_nor_vin(
    db_session: Session, workshop: Workshop
) -> None:
    job = _job(db_session, workshop)
    _work_order(db_session, phone="9261234567", created_at=RECORD_CREATED_AT + timedelta(hours=1))

    stats = planner_service.auto_match_planner_records(db_session)

    assert stats.processed == 1
    assert stats.matched == 0
    db_session.refresh(job)
    assert job.work_order_id is None


def test_writes_an_audit_log_entry(db_session: Session, workshop: Workshop) -> None:
    job = _job(db_session, workshop, phone="9261234567")
    wo = _work_order(
        db_session, phone="9261234567", created_at=RECORD_CREATED_AT + timedelta(hours=1)
    )

    planner_service.auto_match_planner_records(db_session)

    entry = db_session.query(ScheduleAuditLog).filter(ScheduleAuditLog.entity_id == job.id).one()
    assert entry.action == "update"
    assert entry.changes["work_order_id"]["new"] == str(wo.id)
    assert entry.actor_name == planner_service.AUTO_MATCH_ACTOR_NAME
    assert entry.actor_user_id is None
