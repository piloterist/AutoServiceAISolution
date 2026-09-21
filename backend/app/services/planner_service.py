"""CRUD + scheduling validation for the Planner (Слесарный/Кузовной цех).

Слесарный (WorkshopJob): validates the slot is inside the workshop's
working hours/days and doesn't overlap another job on the same post/day.
Кузовной (BodyCar): stages are replaced wholesale on update (delete +
re-insert) - simpler than diffing rows, and matches how the dialog itself
submits the whole stage list as one unit every save.

Every write logs to schedule_audit_log (services/audit_log_service.py),
restricted to the fields a person actually edits - see that module's
docstring for which fields that excludes and why.
"""

from __future__ import annotations

import uuid
from datetime import date, time

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.body_car import BodyCar
from app.models.body_car_stage import BodyCarStage
from app.models.planner_constants import BODY_CAR_COLORS
from app.models.slesarka_status import SlesarkaStatus
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop
from app.models.workshop_job import WorkshopJob
from app.schemas.planner import BodyCarWrite, WorkshopJobWrite
from app.services import audit_log_service

ENTITY_WORKSHOP_JOB = "workshop_job"
ENTITY_BODY_CAR = "body_car"


class SchedulingError(ValueError):
    """A slot/date is outside working hours or overlaps another record -
    always a 422 at the API layer, never a 500."""


class NotFoundError(ValueError):
    pass


# ---- ЗН autocomplete --------------------------------------------------------


def search_work_orders(db: Session, q: str, *, limit: int = 20) -> list[WorkOrder]:
    like = f"%{q}%"
    stmt = (
        select(WorkOrder)
        .where(
            or_(
                WorkOrder.external_number.ilike(like),
                WorkOrder.vehicle_description.ilike(like),
                WorkOrder.vin.ilike(like),
                WorkOrder.customer_name.ilike(like),
            )
        )
        .order_by(WorkOrder.document_date.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


# ---- Слесарный (WorkshopJob) -----------------------------------------------


def _validate_slot(
    db: Session, workshop_id: uuid.UUID, data: WorkshopJobWrite, *, exclude_job_id: uuid.UUID | None
) -> None:
    workshop = db.get(Workshop, workshop_id)
    if workshop is None:
        raise NotFoundError("Workshop not found")

    if data.job_date.weekday() not in workshop.working_days:
        raise SchedulingError("Выбранный день не является рабочим для этого цеха")
    if data.start_time < workshop.start_time or data.end_time > workshop.end_time:
        raise SchedulingError("Время записи выходит за пределы рабочего времени цеха")
    if data.post_number > workshop.posts_count:
        raise SchedulingError("В этом цехе нет такого поста")

    stmt = select(WorkshopJob).where(
        WorkshopJob.workshop_id == workshop_id,
        WorkshopJob.job_date == data.job_date,
        WorkshopJob.post_number == data.post_number,
        WorkshopJob.start_time < data.end_time,
        WorkshopJob.end_time > data.start_time,
    )
    if exclude_job_id is not None:
        stmt = stmt.where(WorkshopJob.id != exclude_job_id)
    if db.scalars(stmt).first() is not None:
        raise SchedulingError("На этом посту уже есть запись на выбранное время")


def list_workshop_jobs(
    db: Session, workshop_id: uuid.UUID, *, date_from: date, date_to: date
) -> list[WorkshopJob]:
    stmt = select(WorkshopJob).where(
        WorkshopJob.workshop_id == workshop_id,
        WorkshopJob.job_date >= date_from,
        WorkshopJob.job_date <= date_to,
    )
    return list(db.scalars(stmt))


_JOB_LOGGED_FIELDS = (
    "work_order_id",
    "car_description",
    "vin",
    "plate",
    "client_name",
    "work_description",
    "job_date",
    "post_number",
    "start_time",
    "end_time",
    "status_id",
)


def create_workshop_job(
    db: Session,
    workshop_id: uuid.UUID,
    data: WorkshopJobWrite,
    *,
    actor_user_id: uuid.UUID | None,
    actor_name: str,
) -> WorkshopJob:
    _validate_slot(db, workshop_id, data, exclude_job_id=None)
    job = WorkshopJob(
        workshop_id=workshop_id,
        created_by_id=actor_user_id,
        updated_by_id=actor_user_id,
        **data.model_dump(),
    )
    db.add(job)
    db.flush()
    audit_log_service.record_change(
        db,
        entity_type=ENTITY_WORKSHOP_JOB,
        entity_id=job.id,
        action="create",
        changes={
            field: {"old": None, "new": _jsonable(getattr(job, field))}
            for field in _JOB_LOGGED_FIELDS
        },
        actor_user_id=actor_user_id,
        actor_name=actor_name,
    )
    db.commit()
    db.refresh(job)
    return job


def update_workshop_job(
    db: Session,
    job_id: uuid.UUID,
    data: WorkshopJobWrite,
    *,
    actor_user_id: uuid.UUID | None,
    actor_name: str,
) -> WorkshopJob:
    job = db.get(WorkshopJob, job_id)
    if job is None:
        raise NotFoundError("Job not found")
    _validate_slot(db, job.workshop_id, data, exclude_job_id=job_id)

    changes = {}
    for field in _JOB_LOGGED_FIELDS:
        old = getattr(job, field)
        new = getattr(data, field)
        if old != new:
            changes[field] = {"old": _jsonable(old), "new": _jsonable(new)}
        setattr(job, field, new)
    job.updated_by_id = actor_user_id

    if changes:
        audit_log_service.record_change(
            db,
            entity_type=ENTITY_WORKSHOP_JOB,
            entity_id=job.id,
            action="update",
            changes=changes,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
        )
    db.commit()
    db.refresh(job)
    return job


def delete_workshop_job(
    db: Session, job_id: uuid.UUID, *, actor_user_id: uuid.UUID | None, actor_name: str
) -> None:
    job = db.get(WorkshopJob, job_id)
    if job is None:
        raise NotFoundError("Job not found")
    audit_log_service.record_change(
        db,
        entity_type=ENTITY_WORKSHOP_JOB,
        entity_id=job.id,
        action="delete",
        changes={
            field: {"old": _jsonable(getattr(job, field)), "new": None}
            for field in _JOB_LOGGED_FIELDS
        },
        actor_user_id=actor_user_id,
        actor_name=actor_name,
    )
    db.delete(job)
    db.commit()


# ---- Кузовной (BodyCar + BodyCarStage) -------------------------------------


def list_body_cars(db: Session, workshop_id: uuid.UUID) -> list[BodyCar]:
    stmt = select(BodyCar).where(BodyCar.workshop_id == workshop_id)
    return list(db.scalars(stmt))


def _next_car_color(db: Session, workshop_id: uuid.UUID) -> str:
    count = (
        db.scalar(
            select(func.count()).select_from(BodyCar).where(BodyCar.workshop_id == workshop_id)
        )
        or 0
    )
    return BODY_CAR_COLORS[count % len(BODY_CAR_COLORS)]


def _stages_snapshot(stages: list[BodyCarStage]) -> list[dict]:
    return [
        {
            "stage_name": s.stage_name,
            "note": s.note,
            "start_date": _jsonable(s.start_date),
            "end_date": _jsonable(s.end_date),
        }
        for s in stages
    ]


_CAR_LOGGED_FIELDS = (
    "work_order_id",
    "car_description",
    "vin",
    "plate",
    "client_name",
    "work_description",
    "status",
)


def create_body_car(
    db: Session,
    workshop_id: uuid.UUID,
    data: BodyCarWrite,
    *,
    actor_user_id: uuid.UUID | None,
    actor_name: str,
) -> BodyCar:
    car = BodyCar(
        workshop_id=workshop_id,
        work_order_id=data.work_order_id,
        car_description=data.car_description,
        vin=data.vin,
        plate=data.plate,
        client_name=data.client_name,
        work_description=data.work_description,
        status=data.status,
        color=_next_car_color(db, workshop_id),
        created_by_id=actor_user_id,
        updated_by_id=actor_user_id,
        stages=[
            BodyCarStage(
                stage_name=s.stage_name,
                note=s.note,
                start_date=s.start_date,
                end_date=s.end_date,
                sort_order=i,
            )
            for i, s in enumerate(data.stages)
        ],
    )
    db.add(car)
    db.flush()

    changes = {f: {"old": None, "new": _jsonable(getattr(car, f))} for f in _CAR_LOGGED_FIELDS}
    changes["stages"] = {"old": None, "new": _stages_snapshot(car.stages)}
    audit_log_service.record_change(
        db,
        entity_type=ENTITY_BODY_CAR,
        entity_id=car.id,
        action="create",
        changes=changes,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
    )
    db.commit()
    db.refresh(car)
    return car


def update_body_car(
    db: Session,
    car_id: uuid.UUID,
    data: BodyCarWrite,
    *,
    actor_user_id: uuid.UUID | None,
    actor_name: str,
) -> BodyCar:
    car = db.get(BodyCar, car_id)
    if car is None:
        raise NotFoundError("Car not found")

    changes = {}
    for field in _CAR_LOGGED_FIELDS:
        old = getattr(car, field)
        new = getattr(data, field)
        if old != new:
            changes[field] = {"old": _jsonable(old), "new": _jsonable(new)}
        setattr(car, field, new)

    old_stages = _stages_snapshot(car.stages)
    car.stages = [
        BodyCarStage(
            stage_name=s.stage_name,
            note=s.note,
            start_date=s.start_date,
            end_date=s.end_date,
            sort_order=i,
        )
        for i, s in enumerate(data.stages)
    ]
    db.flush()
    new_stages = _stages_snapshot(car.stages)
    if old_stages != new_stages:
        changes["stages"] = {"old": old_stages, "new": new_stages}

    car.updated_by_id = actor_user_id

    if changes:
        audit_log_service.record_change(
            db,
            entity_type=ENTITY_BODY_CAR,
            entity_id=car.id,
            action="update",
            changes=changes,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
        )
    db.commit()
    db.refresh(car)
    return car


def delete_body_car(
    db: Session, car_id: uuid.UUID, *, actor_user_id: uuid.UUID | None, actor_name: str
) -> None:
    car = db.get(BodyCar, car_id)
    if car is None:
        raise NotFoundError("Car not found")
    changes = {f: {"old": _jsonable(getattr(car, f)), "new": None} for f in _CAR_LOGGED_FIELDS}
    changes["stages"] = {"old": _stages_snapshot(car.stages), "new": None}
    audit_log_service.record_change(
        db,
        entity_type=ENTITY_BODY_CAR,
        entity_id=car.id,
        action="delete",
        changes=changes,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
    )
    db.delete(car)
    db.commit()


def _jsonable(value):
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def status_lookup(db: Session, status_ids: set[uuid.UUID]) -> dict[uuid.UUID, SlesarkaStatus]:
    if not status_ids:
        return {}
    return {
        s.id: s for s in db.scalars(select(SlesarkaStatus).where(SlesarkaStatus.id.in_(status_ids)))
    }


def work_order_lookup(db: Session, work_order_ids: set[uuid.UUID]) -> dict[uuid.UUID, WorkOrder]:
    if not work_order_ids:
        return {}
    return {w.id: w for w in db.scalars(select(WorkOrder).where(WorkOrder.id.in_(work_order_ids)))}
