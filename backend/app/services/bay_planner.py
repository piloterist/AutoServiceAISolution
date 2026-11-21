"""Видеоконтроль боксов <-> планировщик слесарного цеха и лист «Ошибки».

Бокс N цеха - это пост N планировщика (бокс создаётся по числу постов, sort_order = номер).

Въезд (entry_confirmed):
  - ищем запись плана на этот пост на сегодня с этим номером; сверяем только первые 6 символов
    (в плане регион часто не указан). Запись может быть и позже по времени (машина приехала
    раньше), и раньше (опоздала); берём ближайшую к «сейчас». Найденную переводим в «В работе»;
  - нет записи - создаём на 30 минут, дальше `tick` продлевает её, пока машина в боксе;
  - после выезда запись становится «Готова».
Одновременно на посту может быть несколько записей (машину записали, а приехала другая) -
планировщик рисует их рядом.

Каждая машина в боксе должна быть с заказ-нарядом. Нет заказ-наряда ни по номеру, ни в плане -
заводим ошибку (лист «Ошибки»). Она закрывается сама, когда заказ-наряд появился (или его привязали
к записи плана), либо вручную кнопкой «Исправлено».
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bay import (
    EVENT_EXIT_CONFIRMED,
    ISSUE_NO_WORK_ORDER,
    ISSUE_RESOLVED_AUTO,
    ISSUE_RESOLVED_MANUAL,
    REVIEW_NEEDS,
    Bay,
    BayEvent,
    BayIssue,
    BayOccupancy,
    CameraStatus,
)
from app.models.department import Department
from app.models.slesarka_status import SlesarkaStatus
from app.models.work_order import WorkOrder
from app.models.workshop import WORKSHOP_TYPE_MECHANICAL, Workshop
from app.models.workshop_job import WorkshopJob
from app.services import audit_log_service, gate_service
from app.services.bay_service import (
    CANCELLED_EXIT_MARK,
    OFFLINE_NOTE,
    REENTRY_NOTE,
    SAME_CAR_NOTE,
    SHOP_TZ,
    known_plates,
    normalize_plate,
    plate_from_description,
    same_car_interval,
)
from app.services.planner_service import _JOB_LOGGED_FIELDS, ENTITY_WORKSHOP_JOB, _jsonable
from app.services.settings_service import get_app_settings

logger = structlog.get_logger(__name__)

ACTOR_NAME = "Видеоконтроль"
STATUS_IN_WORK = "В работе"
STATUS_DONE = "Готова"
STATUS_CANCELLED = "Отмена"
PLATE_PREFIX = 6  # регион в плане часто не указан - сверяем только основную часть номера
SLOT_MINUTES = 30
AUTO_WORK_DESCRIPTION = "Создано автоматически: машина заехала в бокс"
# Запись в плане автоматически не создаётся, если номер распознан с меньшей уверенностью.
MIN_CONFIDENCE_FOR_NEW_JOB = Decimal("0.70")
LOW_CONFIDENCE_NOTE = "запись в планировщике не создана: номер распознан с уверенностью ниже 70 %"


class IssueNotFound(Exception):
    pass


# ---- мелочи -----------------------------------------------------------------


def plate_prefix(plate: str | None) -> str | None:
    normalized = normalize_plate(plate)
    return normalized[:PLATE_PREFIX] if normalized and len(normalized) >= PLATE_PREFIX else None


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _at(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


def _ceil_slot(moment: datetime) -> int:
    """Минуты от полуночи, округлённые вверх до границы получаса (13:00:10 -> 13:30)."""
    total = moment.hour * 60 + moment.minute
    if moment.second or moment.microsecond or total % SLOT_MINUTES:
        total = (total // SLOT_MINUTES + 1) * SLOT_MINUTES
    return total


def _status(db: Session, name: str) -> SlesarkaStatus | None:
    return db.scalars(select(SlesarkaStatus).where(SlesarkaStatus.name == name)).first()


def _snapshot(job: WorkshopJob) -> dict:
    return {field: getattr(job, field) for field in _JOB_LOGGED_FIELDS}


def _log(db: Session, job: WorkshopJob, before: dict | None) -> None:
    """Запись в журнал планировщика: что поменял видеоконтроль."""
    if before is None:
        action = "create"
        changes = {f: {"old": None, "new": _jsonable(getattr(job, f))} for f in _JOB_LOGGED_FIELDS}
    else:
        action = "update"
        changes = {
            f: {"old": _jsonable(before[f]), "new": _jsonable(getattr(job, f))}
            for f in _JOB_LOGGED_FIELDS
            if before[f] != getattr(job, f)
        }
    if not changes:
        return
    audit_log_service.record_change(
        db,
        entity_type=ENTITY_WORKSHOP_JOB,
        entity_id=job.id,
        action=action,
        changes=changes,
        actor_user_id=None,
        actor_name=ACTOR_NAME,
        work_order_id=job.work_order_id,
        car_description=job.car_description,
    )


def _job_prefix(db: Session, job: WorkshopJob) -> str | None:
    """Номер записи плана: введённый вручную, иначе из привязанного заказ-наряда."""
    prefix = plate_prefix(job.plate)
    if prefix or job.work_order_id is None:
        return prefix
    work_order = db.get(WorkOrder, job.work_order_id)
    if work_order is None:
        return None
    return plate_prefix(plate_from_description(work_order.vehicle_description))


def _fill_from_work_order(db: Session, job: WorkshopJob, work_order_id: uuid.UUID) -> None:
    job.work_order_id = work_order_id
    work_order = db.get(WorkOrder, work_order_id)
    if work_order is None:
        return
    job.car_description = job.car_description or work_order.vehicle_description
    job.client_name = job.client_name or work_order.customer_name
    job.vin = job.vin or work_order.vin


# ---- въезд ------------------------------------------------------------------


def _find_planned_job(
    db: Session,
    workshop: Workshop,
    post: int,
    moment: datetime,
    prefix: str | None,
    *,
    any_post: bool = False,
) -> WorkshopJob | None:
    """Запись плана на этот номер. any_post: искать на всех постах цеха, а не только на `post`;
    при совпадении записи на своём и чужом посту предпочитается своя."""
    if prefix is None:
        return None
    closed = {s.id for s in (_status(db, STATUS_DONE), _status(db, STATUS_CANCELLED)) if s}
    conditions = [
        WorkshopJob.workshop_id == workshop.id,
        WorkshopJob.job_date == moment.date(),
    ]
    if not any_post:
        conditions.append(WorkshopJob.post_number == post)
    jobs = db.scalars(select(WorkshopJob).where(*conditions)).all()
    candidates = [
        job for job in jobs if job.status_id not in closed and _job_prefix(db, job) == prefix
    ]
    now = _minutes(moment.time())

    def distance(job: WorkshopJob) -> tuple[int, int, int]:
        start, end = _minutes(job.start_time), _minutes(job.end_time)
        other_post = 0 if job.post_number == post else 1
        if start <= now < end:
            return 0, other_post, 0  # идёт сейчас
        if start > now:
            return 1, other_post, start - now  # приехала раньше: ближайшая впереди
        return 2, other_post, now - end  # опоздала: последняя из прошедших

    return min(candidates, key=distance) if candidates else None


def _create_job(
    db: Session,
    workshop: Workshop,
    post: int,
    moment: datetime,
    event: BayEvent,
    *,
    from_day_start: bool = False,
) -> WorkshopJob | None:
    """from_day_start: запись на новый день для машины, что стоит в боксе с прошлых суток, -
    она начинается с начала рабочего дня, а не с момента, когда это заметили."""
    if moment.weekday() not in workshop.working_days or not 1 <= post <= workshop.posts_count:
        return None
    start = _minutes(workshop.start_time)
    if not from_day_start:
        start = max(_minutes(moment.time()), start)
    end = min(start + SLOT_MINUTES, _minutes(workshop.end_time))
    if end <= start:
        return None  # въезд после закрытия цеха: записи не создаём
    status = _status(db, STATUS_IN_WORK)
    job = WorkshopJob(
        workshop_id=workshop.id,
        post_number=post,
        job_date=moment.date(),
        start_time=_at(start),
        end_time=_at(end),
        plate=event.plate,
        status_id=status.id if status else None,
        work_description=AUTO_WORK_DESCRIPTION,
    )
    if event.work_order_id:
        _fill_from_work_order(db, job, event.work_order_id)
    db.add(job)
    db.flush()
    _log(db, job, None)
    return job


def _actual_start(db: Session, job: WorkshopJob, arrived: datetime) -> tuple[time, time] | None:
    """Запись начинается с фактического заезда (с минуты заезда, как и записи, что создаются при
    заезде), и когда машина приехала раньше плана, и когда позже. Не раньше начала рабочего дня
    (ручная правка записи вне часов цеха не принимается). Наложение на соседние записи
    допустимо: доска ставит пересекающиеся записи рядом. Если машина приехала после планового
    конца, запись получает слот в 30 минут от заезда (дальше её продлевает tick, пока машина
    стоит). Возвращает (начало, конец); None - сдвигать нечего."""
    if job.job_date != arrived.date():
        return None
    start = _minutes(arrived.time())
    workshop = db.get(Workshop, job.workshop_id)
    day_end = 24 * 60
    if workshop is not None:
        start = max(start, _minutes(workshop.start_time))
        day_end = _minutes(workshop.end_time)
    if start == _minutes(job.start_time) or start >= day_end:
        return None
    end = _minutes(job.end_time)
    if end <= start:
        end = min(start + SLOT_MINUTES, day_end)
    return _at(start), _at(end)


def _start_job(db: Session, job: WorkshopJob, event: BayEvent) -> None:
    before = _snapshot(job)
    status = _status(db, STATUS_IN_WORK)
    if status:
        job.status_id = status.id
    # Начало записи - фактический заезд (2026-11-20: заезд в 09:48, запись с 10:00; Audi ждали в
    # 10:30, приехала в 10:35).
    actual = _actual_start(db, job, event.occurred_at.astimezone(SHOP_TZ))
    if actual is not None:
        job.start_time, job.end_time = actual
    job.plate = job.plate or event.plate
    if event.work_order_id and job.work_order_id is None:
        _fill_from_work_order(db, job, event.work_order_id)
    _log(db, job, before)


def _open_issue(db: Session, bay: Bay, event: BayEvent, interval: BayOccupancy) -> None:
    exists = db.scalars(
        select(BayIssue).where(BayIssue.occupancy_id == interval.id, BayIssue.resolved_at.is_(None))
    ).first()
    if exists:
        return
    who = f"Машина {event.plate}" if event.plate else "Машина (номер не распознан)"
    db.add(
        BayIssue(
            bay_id=bay.id,
            occupancy_id=interval.id,
            entry_event_id=event.id,
            kind=ISSUE_NO_WORK_ORDER,
            plate=event.plate,
            message=f"{who} стоит в боксе «{bay.name}», а заказ-наряда по её номеру нет.",
            occurred_at=event.occurred_at,
        )
    )
    logger.warning("bay_issue_no_work_order", bay=bay.name, plate=event.plate)


def on_entry(db: Session, event: BayEvent) -> None:
    """Вызывается после записи подтверждённого въезда (заказ-наряд по номеру уже определён)."""
    interval = db.scalars(
        select(BayOccupancy).where(BayOccupancy.entry_event_id == event.id)
    ).first()
    bay = db.get(Bay, event.bay_id)
    if interval is None:
        # Въезд не создал заезда. Если он - возвращение машины, «уехавшей» раньше времени
        # (REENTRY_NOTE), отменяем тот выезд: бокс снова занят прежней машиной.
        if event.note and (REENTRY_NOTE in event.note or SAME_CAR_NOTE in event.note):
            _cancel_false_exit(db, event)
        return
    if bay is None:
        return
    workshop = db.get(Workshop, bay.workshop_id)
    if workshop is not None and workshop.workshop_type == WORKSHOP_TYPE_MECHANICAL:
        moment = event.occurred_at.astimezone(SHOP_TZ)
        track_posts = get_app_settings(db).control_posts_enabled
        job = _find_planned_job(
            db,
            workshop,
            bay.sort_order,
            moment,
            plate_prefix(event.plate),
            any_post=not track_posts,
        )
        if job is not None:
            _start_job(db, job, event)  # запись начинается на своём посту, не переезжает
        elif event.ocr_confidence is not None and event.ocr_confidence < MIN_CONFIDENCE_FOR_NEW_JOB:
            # Номер, скорее всего, прочитан неверно: записи на несуществующую машину не плодим.
            event.note = (
                f"{event.note}; {LOW_CONFIDENCE_NOTE}" if event.note else LOW_CONFIDENCE_NOTE
            )
        else:
            job = _create_job(db, workshop, bay.sort_order, moment, event)
        if job is not None:
            interval.workshop_job_id = job.id
            if event.work_order_id is None:
                event.work_order_id = job.work_order_id  # заказ-наряд мог быть уже в плане
    if event.work_order_id is None:
        _open_issue(db, bay, event, interval)
    db.commit()


def _cancel_false_exit(db: Session, event: BayEvent) -> None:
    """Выезд, после которого машина тут же «заехала» обратно, был ложным (номер закрыли люди и
    т. п.): интервал занятости открывается снова, запись плана возвращается в «В работе»."""
    interval = same_car_interval(db, event) if SAME_CAR_NOTE in (event.note or "") else None
    if interval is not None:
        exit_event = db.get(BayEvent, interval.exit_event_id) if interval.exit_event_id else None
    else:
        exit_event = db.scalars(
            select(BayEvent)
            .where(
                BayEvent.bay_id == event.bay_id,
                BayEvent.event_type == EVENT_EXIT_CONFIRMED,
                BayEvent.occurred_at <= event.occurred_at,
            )
            .order_by(BayEvent.occurred_at.desc())
            .limit(1)
        ).first()
        if exit_event is None:
            return
        interval = db.scalars(
            select(BayOccupancy).where(BayOccupancy.exit_event_id == exit_event.id)
        ).first()
    if interval is None or exit_event is None:
        return
    interval.ended_at = None
    interval.exit_event_id = None
    after_offline = OFFLINE_NOTE in (exit_event.note or "")
    note = f"{CANCELLED_EXIT_MARK}: " + (
        "узел снова на связи, машина на месте" if after_offline else "машина вернулась в кадр"
    )
    exit_event.note = f"{exit_event.note}; {note}" if exit_event.note else note
    today = event.occurred_at.astimezone(SHOP_TZ).date()
    if interval.workshop_job_id is not None:
        job = db.get(WorkshopJob, interval.workshop_job_id)
        in_work = _status(db, STATUS_IN_WORK)
        # Запись прошлых суток остаётся закрытой: запись на сегодня создаст _roll_over_open_jobs.
        if (
            job is not None
            and in_work is not None
            and job.job_date >= today
            and job.status_id != in_work.id
        ):
            before = _snapshot(job)
            job.status_id = in_work.id
            _log(db, job, before)
    db.commit()


# ---- выезд ------------------------------------------------------------------


def on_exit(db: Session, event: BayEvent) -> None:
    interval = db.scalars(
        select(BayOccupancy).where(BayOccupancy.exit_event_id == event.id)
    ).first()
    if interval is None or interval.workshop_job_id is None:
        return
    job = db.get(WorkshopJob, interval.workshop_job_id)
    done = _status(db, STATUS_DONE)
    if job is not None and done is not None and job.status_id != done.id:
        before = _snapshot(job)
        job.status_id = done.id
        # Запись заканчивается, когда машина уехала (с точностью до минуты, как и начало при
        # раннем заезде), а не в запланированное время: иначе на доске блок тянется дальше выезда
        # (2026-11-20: выезд в 10:33, запись до 12:30). Короткий заезд (лампочку заменить) - тоже
        # запись, но не короче минуты. Старые значения остаются в журнале планировщика.
        left_at = event.occurred_at.astimezone(SHOP_TZ)
        if job.job_date == left_at.date():
            new_end = max(_minutes(left_at.time()), _minutes(job.start_time) + 1)
            if new_end < _minutes(job.end_time):
                job.end_time = _at(new_end)
        _log(db, job, before)
    db.commit()


# ---- периодическая работа (раз в минуту) -------------------------------------


def _extend_open_jobs(db: Session, now: datetime) -> int:
    local = now.astimezone(SHOP_TZ)
    extended = 0
    rows = db.execute(
        select(BayOccupancy, WorkshopJob)
        .join(WorkshopJob, WorkshopJob.id == BayOccupancy.workshop_job_id)
        .where(BayOccupancy.ended_at.is_(None), WorkshopJob.job_date == local.date())
    ).all()
    for _, job in rows:
        if _minutes(local.time()) < _minutes(job.end_time):
            continue
        workshop = db.get(Workshop, job.workshop_id)
        new_end = _ceil_slot(local)
        if workshop is not None:
            new_end = min(new_end, _minutes(workshop.end_time))
        if new_end > _minutes(job.end_time):
            before = _snapshot(job)
            job.end_time = _at(new_end)
            _log(db, job, before)
            extended += 1
    return extended


def _roll_over_open_jobs(db: Session, now: datetime) -> int:
    """Машина стоит в боксе дольше суток: на каждый новый рабочий день записи плана своя, с начала
    рабочего дня (вчерашняя закрывается «Готова»). Запись на сегодня берётся из плана мастера,
    если он её уже завёл, иначе создаётся."""
    local = now.astimezone(SHOP_TZ)
    rows = db.execute(
        select(BayOccupancy, WorkshopJob, Bay)
        .join(WorkshopJob, WorkshopJob.id == BayOccupancy.workshop_job_id)
        .join(Bay, Bay.id == BayOccupancy.bay_id)
        .where(BayOccupancy.ended_at.is_(None), WorkshopJob.job_date < local.date())
    ).all()
    done = _status(db, STATUS_DONE)
    cancelled = _status(db, STATUS_CANCELLED)
    rolled = 0
    for interval, old_job, bay in rows:
        workshop = db.get(Workshop, bay.workshop_id)
        if (
            workshop is None
            or workshop.workshop_type != WORKSHOP_TYPE_MECHANICAL
            or local.weekday() not in workshop.working_days
            or not workshop.start_time <= local.time() < workshop.end_time
        ):
            continue
        entry = db.get(BayEvent, interval.entry_event_id)
        if entry is None:
            continue
        track_posts = get_app_settings(db).control_posts_enabled
        job = _find_planned_job(
            db,
            workshop,
            bay.sort_order,
            local,
            plate_prefix(interval.plate),
            any_post=not track_posts,
        )
        if job is not None:
            _start_job(db, job, entry)
        else:
            job = _create_job(db, workshop, bay.sort_order, local, entry, from_day_start=True)
        if job is None:
            continue
        if old_job.status_id not in {s.id for s in (done, cancelled) if s} and done is not None:
            before = _snapshot(old_job)
            old_job.status_id = done.id
            _log(db, old_job, before)
        interval.workshop_job_id = job.id
        db.flush()
        rolled += 1
    return rolled


def _resolve_found_work_orders(db: Session) -> int:
    issues = db.scalars(
        select(BayIssue).where(BayIssue.resolved_at.is_(None), BayIssue.kind == ISSUE_NO_WORK_ORDER)
    ).all()
    if not issues:
        return 0
    known = {k["plate"]: k["work_order_id"] for k in known_plates(db)}
    resolved = 0
    for issue in issues:
        interval = db.get(BayOccupancy, issue.occupancy_id) if issue.occupancy_id else None
        job = (
            db.get(WorkshopJob, interval.workshop_job_id)
            if interval is not None and interval.workshop_job_id
            else None
        )
        work_order_id = known.get(issue.plate) or (job.work_order_id if job else None)
        if work_order_id is None:
            continue
        event = db.get(BayEvent, issue.entry_event_id) if issue.entry_event_id else None
        if event is not None:
            event.work_order_id = work_order_id
        if job is not None and job.work_order_id is None:
            before = _snapshot(job)
            _fill_from_work_order(db, job, work_order_id)
            _log(db, job, before)
        issue.resolved_at = datetime.now(UTC)
        issue.resolution = ISSUE_RESOLVED_AUTO
        issue.resolved_by = ACTOR_NAME
        issue.resolution_note = "Заказ-наряд появился"
        resolved += 1
    return resolved


# Если узел камеры не выходил на связь дольше этого срока, открытый заезд закрывается сам: пока
# узел выключен (ночью, сломался), он ничего не видит, а при запуске узел принимает «бокс занят»
# за правду и не замечает, что машина уехала или стоит уже другая. После закрытия узел стартует
# с «бокс свободен» и сам увидит то, что стоит в боксе.
NODE_OFFLINE_CLOSE = timedelta(hours=3)


def _close_orphaned(db: Session, now: datetime) -> int:
    rows = db.execute(
        select(BayOccupancy, Bay)
        .join(Bay, Bay.id == BayOccupancy.bay_id)
        .where(BayOccupancy.ended_at.is_(None), Bay.camera_code.is_not(None))
    ).all()
    closed = 0
    for interval, bay in rows:
        status = db.get(CameraStatus, bay.camera_code)
        if status is None or now - status.seen_at < NODE_OFFLINE_CLOSE:
            continue
        entry = db.get(BayEvent, interval.entry_event_id)
        if entry is not None and entry.source == "manual":
            continue  # заезд, введённый оператором руками, узел не касается
        ended = max(status.seen_at, interval.started_at)
        exit_event = BayEvent(
            bay_id=bay.id,
            event_type=EVENT_EXIT_CONFIRMED,
            occurred_at=ended,
            plate=interval.plate,
            review_status=REVIEW_NEEDS,
            source="auto",
            note=OFFLINE_NOTE,
        )
        db.add(exit_event)
        db.flush()
        interval.ended_at = ended
        interval.exit_event_id = exit_event.id
        db.flush()
        on_exit(db, exit_event)  # запись плана - «Готова»
        closed += 1
    return closed


def tick(db: Session, now: datetime | None = None) -> tuple[int, int]:
    """(записей продлено, ошибок закрыто автоматически)."""
    now = now or datetime.now(UTC)
    _close_orphaned(db, now)
    _roll_over_open_jobs(db, now)
    extended = _extend_open_jobs(db, now)
    resolved = _resolve_found_work_orders(db)
    gate_service.reconcile(db)  # кузов: машина в цеху, чья карточка плана появилась позже
    db.commit()
    return extended, resolved


# ---- лист «Ошибки» ----------------------------------------------------------


def count_open_issues(db: Session) -> int:
    return len(db.scalars(select(BayIssue.id).where(BayIssue.resolved_at.is_(None))).all())


def list_issues(db: Session, *, status: str = "all") -> list[dict]:
    query = (
        select(BayIssue, Bay, Workshop, Department)
        .outerjoin(Bay, Bay.id == BayIssue.bay_id)
        .outerjoin(Workshop, Workshop.id == Bay.workshop_id)
        .outerjoin(Department, Department.id == Workshop.department_id)
        .order_by(BayIssue.occurred_at.desc())
    )
    if status == "open":
        query = query.where(BayIssue.resolved_at.is_(None))
    elif status == "resolved":
        query = query.where(BayIssue.resolved_at.is_not(None))
    items = []
    for issue, bay, workshop, department in db.execute(query.limit(500)).all():
        items.append(
            {
                "id": issue.id,
                "bay_id": bay.id if bay else None,
                "bay_name": bay.name if bay else "Импорт из 1С",
                "workshop_label": (
                    f"{department.name} / {workshop.workshop_type}"
                    if bay and workshop and department
                    else "Интеграция"
                ),
                "kind": issue.kind,
                "plate": issue.plate,
                "message": issue.message,
                "occurred_at": issue.occurred_at,
                "entry_event_id": issue.entry_event_id,
                "resolved_at": issue.resolved_at,
                "resolution": issue.resolution,
                "resolved_by": issue.resolved_by,
                "resolution_note": issue.resolution_note,
            }
        )
    return items


def resolve_issue(db: Session, issue_id: uuid.UUID, *, who: str, note: str | None) -> BayIssue:
    issue = db.get(BayIssue, issue_id)
    if issue is None:
        raise IssueNotFound(str(issue_id))
    if issue.resolved_at is None:
        issue.resolved_at = datetime.now(UTC)
        issue.resolution = ISSUE_RESOLVED_MANUAL
        issue.resolved_by = who
        issue.resolution_note = (note or "").strip() or None
        db.commit()
        db.refresh(issue)
    return issue
