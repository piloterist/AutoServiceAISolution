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

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.body_car import BodyCar
from app.models.body_car_stage import BodyCarStage
from app.models.employee import Employee
from app.models.planner_constants import BODY_CAR_COLORS
from app.models.slesarka_status import SlesarkaStatus
from app.models.user import User
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop
from app.models.workshop_job import WorkshopJob
from app.schemas.planner import BodyCarWrite, WorkshopJobWrite
from app.services import audit_log_service
from app.services.fivesystems_client import WorkOrderLookupResult
from app.services.internal_order_rules import normalize_vin

ENTITY_WORKSHOP_JOB = "workshop_job"
ENTITY_BODY_CAR = "body_car"

# WorkOrder.status is plain free text (1C's own value, e.g. "Закрыт"/
# "Выполнен" on this deployment - see WorkOrder.status's own docstring, no
# enum). Gated behind AppSettings.planner_search_exclude_closed_orders
# (off by default) rather than baked unconditionally into the query below,
# since another deployment's status wording may differ entirely.
CLOSED_WORK_ORDER_STATUSES = ("Закрыт", "Выполнен")


class SchedulingError(ValueError):
    """A slot/date is outside working hours or overlaps another record -
    always a 422 at the API layer, never a 500."""


class NotFoundError(ValueError):
    pass


# ---- ЗН autocomplete --------------------------------------------------------


def search_work_orders(
    db: Session, q: str, *, exclude_closed: bool = False, limit: int = 20
) -> list[WorkOrder]:
    like = f"%{q}%"
    conditions = [
        or_(
            WorkOrder.external_number.ilike(like),
            WorkOrder.vehicle_description.ilike(like),
            WorkOrder.vin.ilike(like),
            WorkOrder.customer_name.ilike(like),
        )
    ]
    if exclude_closed:
        # A work order with no status at all is never hidden - nothing to
        # match against (see CLOSED_WORK_ORDER_STATUSES's own comment).
        conditions.append(
            or_(WorkOrder.status.is_(None), WorkOrder.status.notin_(CLOSED_WORK_ORDER_STATUSES))
        )
    stmt = (
        select(WorkOrder).where(*conditions).order_by(WorkOrder.document_date.desc()).limit(limit)
    )
    return list(db.scalars(stmt))


def get_or_create_stub_work_order(
    db: Session, result: WorkOrderLookupResult
) -> tuple[WorkOrder, bool]:
    """Finds or creates the WorkOrder a live 5Systems plate lookup
    corresponds to, keyed by the same (source_system, external_number)
    the real 1C import upserts on - so the next day's real import lands on
    this exact same row and fills in everything this stub couldn't get
    (labor/part lines, payment history, internal-order flags, the rest of
    the fields this module never touches).

    Deliberately INSERT ... ON CONFLICT DO NOTHING, never DO UPDATE: if a
    row already exists here, it was either populated by a real import
    (richer than anything this lookup could ever produce - must not be
    degraded back to a stub) or by an earlier lookup for the same plate
    (nothing new to add). Either way, the existing row wins as-is.

    Returns (work_order, inserted) - inserted is False when the row already
    existed (the ON CONFLICT DO NOTHING branch fired, so this INSERT
    affected zero rows) - the caller uses this to decide whether to sync
    that ЗН's own data into any Planner record already linked to it (see
    sync_planner_records_from_work_order) - only meaningful when this
    wasn't a brand new stub, which by definition has nothing yet to sync.
    """
    table = WorkOrder.__table__
    values = {
        "external_number": result.external_number,
        "source_system": "alpha-auto",
        "document_date": result.document_date,
        "customer_name": result.customer_name,
        "vehicle_description": result.vehicle_description,
        "vin": result.vin,
        # NOT NULL on the model - 0 here means "not priced yet/unknown",
        # not a real figure; corrected the same way every other field here
        # is, by the next real 1C import.
        "amount": result.amount if result.amount is not None else Decimal("0"),
    }
    stmt = (
        pg_insert(table)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[table.c.source_system, table.c.external_number],
        )
        .returning(table.c.id)
    )
    # RETURNING - not rowcount, which psycopg reports unreliably for a
    # DO NOTHING statement (same reasoning as the xmax RETURNING trick in
    # import_service.py's _upsert_work_order, just simpler here since
    # DO NOTHING never touches an existing row - no row back means the
    # conflict branch fired and nothing was inserted).
    inserted = db.execute(stmt).scalar() is not None
    db.commit()

    row = db.scalar(
        select(WorkOrder).where(
            WorkOrder.source_system == "alpha-auto",
            WorkOrder.external_number == result.external_number,
        )
    )
    if row is None:  # pragma: no cover - the insert above guarantees a row exists
        raise NotFoundError("Failed to create or find the looked-up work order")
    return row, inserted


def sync_planner_records_from_work_order(
    db: Session,
    work_order: WorkOrder,
    plate: str | None,
    phone: str | None,
    *,
    actor_user_id: uuid.UUID | None,
    actor_name: str,
) -> None:
    """Called after a live 5Systems lookup turns out to be for a ЗН that
    ALREADY existed (see get_or_create_stub_work_order's `inserted` flag) -
    an operator re-confirming a car whose ЗН is already known to us. Any
    WorkshopJob/BodyCar record already linked to this work_order_id gets
    its car_description/vin/client_name/phone refreshed from the ЗН's own
    (possibly since-enriched-by-a-real-1C-import) data - `plate` and `phone`
    come from the lookup result itself, not from work_order: WorkOrder has
    no plate column at all (1C's own export contract doesn't carry one),
    and WorkOrder.phone is deliberately never written by this integration
    (see get_or_create_stub_work_order) - the caller passes whichever
    phone it has (the fresh 5Systems lookup's own, falling back to
    work_order.phone if that lookup didn't find one).

    Never overwrites a field with an empty one - the ЗН/lookup not having a
    value yet must not blank out something already typed by hand.
    """
    new_values = {
        "car_description": work_order.vehicle_description,
        "vin": work_order.vin,
        "plate": plate,
        "client_name": work_order.customer_name,
        "phone": phone,
    }

    jobs = list(db.scalars(select(WorkshopJob).where(WorkshopJob.work_order_id == work_order.id)))
    cars = list(db.scalars(select(BodyCar).where(BodyCar.work_order_id == work_order.id)))
    if not jobs and not cars:
        return

    for job in jobs:
        changes = {}
        for field, new in new_values.items():
            if not new:
                continue
            old = getattr(job, field)
            if old != new:
                changes[field] = {"old": old, "new": new}
                setattr(job, field, new)
        if changes:
            job.updated_by_id = actor_user_id
            audit_log_service.record_change(
                db,
                entity_type=ENTITY_WORKSHOP_JOB,
                entity_id=job.id,
                action="update",
                changes=changes,
                actor_user_id=actor_user_id,
                actor_name=actor_name,
                work_order_id=job.work_order_id,
                car_description=job.car_description,
            )

    for car in cars:
        changes = {}
        for field, new in new_values.items():
            if not new:
                continue
            old = getattr(car, field)
            if old != new:
                changes[field] = {"old": old, "new": new}
                setattr(car, field, new)
        if changes:
            car.updated_by_id = actor_user_id
            audit_log_service.record_change(
                db,
                entity_type=ENTITY_BODY_CAR,
                entity_id=car.id,
                action="update",
                changes=changes,
                actor_user_id=actor_user_id,
                actor_name=actor_name,
                work_order_id=car.work_order_id,
                car_description=car.car_description,
            )

    db.commit()


# ---- Автосопоставление с ЗН по телефону/VIN --------------------------------

AUTO_MATCH_ACTOR_NAME = "Автосопоставление (телефон/VIN)"
AUTO_MATCH_WINDOW_DAYS = 3


def _normalize_phone(value: str | None) -> str:
    """Last 10 digits - same convention as leads_service/telephony_stats_service's
    own _normalize_phone (duplicated rather than shared, same as those two
    already are) - so a planner record's hand-typed/ЗН-sourced phone
    compares equal to WorkOrder.phone regardless of formatting
    ("+7 (926) 1642018" vs "+7 926 164-20-18")."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else digits


@dataclass
class AutoMatchStats:
    processed: int = 0
    matched: int = 0


def _find_match_candidate(
    db: Session, *, phone: str, vin: str | None, created_at: datetime
) -> WorkOrder | None:
    """Earliest WorkOrder created in [created_at, created_at + 3 days]
    matching this planner record's own phone or VIN (either is enough) -
    see auto_match_planner_records. The candidate set is bounded by the
    date window (normally tiny), so it's fetched once per record and
    filtered in Python - WorkOrder.phone is raw 1C passthrough (not
    normalized), so a SQL-level equality check wouldn't match anyway."""
    window_end = created_at + timedelta(days=AUTO_MATCH_WINDOW_DAYS)
    candidates = db.scalars(
        select(WorkOrder)
        .where(WorkOrder.created_at >= created_at, WorkOrder.created_at <= window_end)
        .order_by(WorkOrder.created_at)
    )
    for candidate in candidates:
        if phone and _normalize_phone(candidate.phone) == phone:
            return candidate
        if vin and normalize_vin(candidate.vin) == vin:
            return candidate
    return None


def _apply_auto_match(db: Session, record: WorkshopJob | BodyCar, *, entity_type: str) -> bool:
    phone = _normalize_phone(record.phone) if record.phone else ""
    vin = normalize_vin(record.vin) if record.vin else None
    if not phone and not vin:
        return False

    work_order = _find_match_candidate(db, phone=phone, vin=vin, created_at=record.created_at)
    if work_order is None:
        return False

    changes: dict[str, dict] = {"work_order_id": {"old": None, "new": _jsonable(work_order.id)}}
    record.work_order_id = work_order.id

    # Never overwrites a field already present - same rule as
    # sync_planner_records_from_work_order above (a value typed by hand
    # must not be blanked out/replaced by the ЗН's own, possibly less
    # complete, data).
    new_values = {
        "car_description": work_order.vehicle_description,
        "vin": work_order.vin,
        "client_name": work_order.customer_name,
        "phone": work_order.phone,
    }
    for field, new in new_values.items():
        if not new or getattr(record, field):
            continue
        changes[field] = {"old": None, "new": new}
        setattr(record, field, new)

    audit_log_service.record_change(
        db,
        entity_type=entity_type,
        entity_id=record.id,
        action="update",
        changes=changes,
        actor_user_id=None,
        actor_name=AUTO_MATCH_ACTOR_NAME,
        work_order_id=record.work_order_id,
        car_description=record.car_description,
    )
    return True


def auto_match_planner_records(db: Session) -> AutoMatchStats:
    """Automatically links an unlinked WorkshopJob/BodyCar (work_order_id
    still NULL) to a WorkOrder imported shortly afterward, when they
    clearly belong to the same real visit - matched by phone OR VIN
    (either is enough), within [record.created_at, +3 days] (product ask,
    2026-10-05: a planner record is often created by phone/VIN ahead of
    the real 1C import, which can lag by days - 1C's own created_at never
    predates the planner record it corresponds to). Already-linked records
    are skipped entirely, by construction (only unlinked ones are
    queried) - this never re-points or second-guesses a link a person
    already made by hand. See services/planner_match_relay.py for the
    background schedule that calls this, and the "Выполнить сейчас" button
    in Settings for an on-demand run."""
    stats = AutoMatchStats()
    jobs = list(db.scalars(select(WorkshopJob).where(WorkshopJob.work_order_id.is_(None))))
    cars = list(db.scalars(select(BodyCar).where(BodyCar.work_order_id.is_(None))))
    stats.processed = len(jobs) + len(cars)

    for job in jobs:
        if _apply_auto_match(db, job, entity_type=ENTITY_WORKSHOP_JOB):
            stats.matched += 1
    for car in cars:
        if _apply_auto_match(db, car, entity_type=ENTITY_BODY_CAR):
            stats.matched += 1

    db.commit()
    return stats


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
    "phone",
    "employee_id",
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
        work_order_id=job.work_order_id,
        car_description=job.car_description,
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
            work_order_id=job.work_order_id,
            car_description=job.car_description,
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
        work_order_id=job.work_order_id,
        car_description=job.car_description,
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
            "employee_id": _jsonable(s.employee_id),
        }
        for s in stages
    ]


_CAR_LOGGED_FIELDS = (
    "work_order_id",
    "car_description",
    "vin",
    "plate",
    "client_name",
    "phone",
    "work_description",
    "status",
    "on_site",
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
        phone=data.phone,
        work_description=data.work_description,
        status=data.status,
        on_site=data.on_site,
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
                employee_id=s.employee_id,
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
        work_order_id=car.work_order_id,
        car_description=car.car_description,
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
            employee_id=s.employee_id,
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
            work_order_id=car.work_order_id,
            car_description=car.car_description,
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
        work_order_id=car.work_order_id,
        car_description=car.car_description,
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


def employee_lookup(db: Session, employee_ids: set[uuid.UUID]) -> dict[uuid.UUID, Employee]:
    if not employee_ids:
        return {}
    return {e.id: e for e in db.scalars(select(Employee).where(Employee.id.in_(employee_ids)))}


def scheduled_work_order_ids(db: Session, work_order_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these ЗН already have a Планировщик record, on either
    цех - feeds the Work Orders list's "Запланирован" Да/Нет column/filter
    (product ask, 2026-10-01)."""
    if not work_order_ids:
        return set()
    body_ids = db.scalars(
        select(BodyCar.work_order_id).where(BodyCar.work_order_id.in_(work_order_ids))
    )
    job_ids = db.scalars(
        select(WorkshopJob.work_order_id).where(WorkshopJob.work_order_id.in_(work_order_ids))
    )
    return set(body_ids) | set(job_ids)


@dataclass
class PlannerRecordRef:
    kind: str  # "body" | "mechanical"
    workshop_id: uuid.UUID
    date: date


def find_planner_record(db: Session, work_order_id: uuid.UUID) -> PlannerRecordRef | None:
    """Which Планировщик record (if any) a ЗН is scheduled on, for the Work
    Order detail page's "Перейти к записи" button (product ask,
    2026-10-01). Кузовной (BodyCar) always wins when a ЗН is scheduled on
    both: "если есть и в слесарке и в кузове, то всегда выбирать кузов".
    `date` is the day the frontend should position the planner's own date
    window on - a BodyCar's earliest stage start (every BodyCar has >=1
    stage, enforced by BodyCarWrite.stages's min_length=1), or a
    WorkshopJob's own job_date.
    """
    car_row = db.execute(
        select(BodyCar.workshop_id, func.min(BodyCarStage.start_date))
        .join(BodyCarStage, BodyCarStage.body_car_id == BodyCar.id)
        .where(BodyCar.work_order_id == work_order_id)
        .group_by(BodyCar.workshop_id)
        .limit(1)
    ).first()
    if car_row is not None:
        return PlannerRecordRef(kind="body", workshop_id=car_row[0], date=car_row[1])

    job_row = db.execute(
        select(WorkshopJob.workshop_id, WorkshopJob.job_date)
        .where(WorkshopJob.work_order_id == work_order_id)
        .limit(1)
    ).first()
    if job_row is not None:
        return PlannerRecordRef(kind="mechanical", workshop_id=job_row[0], date=job_row[1])

    return None


def user_lookup(db: Session, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    """Resolves WorkshopJob/BodyCar.created_by_id to a display name - see
    _job_out/_car_out's read-only "CreatedBy" field (per product ask,
    2026-10-01: "RecId - внутренний номер записи... CreatedBy -
    пользователь, который создал запись, чтобы всегда можно было
    посмотреть")."""
    if not user_ids:
        return {}
    return {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
