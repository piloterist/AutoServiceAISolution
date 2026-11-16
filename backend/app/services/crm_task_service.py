"""Доска задач CRM (product ask, 2026-11-15).

Телефон клиента берут на контроль кнопкой «На контроль» у звонка (telephony) - появляется карточка
(CrmTask) в столбце «На контроле». Дальше карточка едет по столбцам:

  На контроле -> Записан на осмотр : в планировщике кузовного цеха (BodyCar) появилась запись
                                      с этим телефоном и этапом «Осмотр»;
  Записан на осмотр -> Думает      : по телефону создана заявка на ремонт (только из «Записан
                                      на осмотр»);
  любой активный -> Заказ-наряд    : по телефону появился заказ-наряд;
  любой -> Отказ                   : только руками, с обязательной причиной.

Всё, что появляется по телефону, должно быть позже звонка (иначе зацепится прошлое клиента); после
ручного перемещения - позже перемещения, а заявка - ещё и позже записи на осмотр. Автоматика только
двигает карточку вперёд (синхронизация при каждом чтении доски/счётчика, ничего не вычисляется на
лету) и не трогает «Отказ» и «Заказ-наряд»: отказ - решение человека, заказ-наряд - конец пути.
Из «Заказ-наряда» руками не вытащить, в него руками не положить.

Карточка в «На контроле» краснеет: розовая через crm_task_warn_days, красная через
crm_task_overdue_days от попадания в столбец. Счётчик планировщика - число карточек цеха, дошедших
хотя бы до розового срока.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.body_car import BodyCar
from app.models.body_car_stage import BodyCarStage
from app.models.call_record import CallRecord
from app.models.crm_task import (
    TASK_STATUS_CONTROL,
    TASK_STATUS_INSPECTION,
    TASK_STATUS_REFUSED,
    TASK_STATUS_THINKING,
    TASK_STATUS_WORK_ORDER,
    TASK_STATUSES,
    CrmTask,
    CrmTaskAction,
    CrmTaskComment,
)
from app.models.employee import Employee
from app.models.work_order import DOC_TYPE_REPAIR_REQUEST, DOC_TYPE_WORK_ORDER, WorkOrder
from app.models.workshop import Workshop
from app.models.workshop_job import WorkshopJob
from app.services import planner_service
from app.services.request_control_service import _aware
from app.services.request_control_service import _phones as phone_numbers
from app.services.settings_service import get_app_settings

_MSK = timezone(timedelta(hours=3))
INSPECTION_STAGE = "Осмотр"
# Карточки, за которыми ещё следит автоматика.
ACTIVE_STATUSES = (TASK_STATUS_CONTROL, TASK_STATUS_INSPECTION, TASK_STATUS_THINKING)

Alert = Literal["warn", "overdue"]


class CrmTaskError(Exception):
    """Base class - the endpoint maps each subclass to an HTTP status."""


class CrmTaskNotFound(CrmTaskError):
    pass


class CrmTaskInvalid(CrmTaskError):
    pass


@dataclass
class OverdueCount:
    warn_count: int  # дошли хотя бы до розового срока (включая красные)
    overdue_count: int  # дошли до красного срока
    warn_days: int
    overdue_days: int


# ---- создание ------------------------------------------------------------------


def create_from_call(
    db: Session,
    call_id: uuid.UUID,
    *,
    workshop_id: uuid.UUID | None,
    employee_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None,
    actor_name: str,
) -> tuple[CrmTask, bool]:
    """Берёт телефон звонка на контроль в выбранном цехе (цех обязателен: по нему карточка
    попадает в фильтр доски и в счётчик планировщика). Если этот телефон уже ведётся (карточка не
    в «Отказе» и не в «Заказ-наряде») - возвращает её, ничего не создавая (created=False)."""
    if workshop_id is None:
        raise CrmTaskInvalid("Выберите цех")
    if db.get(Workshop, workshop_id) is None:
        raise CrmTaskInvalid("Цех не найден")
    if employee_id is not None:
        employee = db.get(Employee, employee_id)
        if employee is None:
            raise CrmTaskInvalid("Сотрудник не найден")
        # Сотрудник без цеха (в справочнике цех не указан) подходит к любому цеху.
        if employee.workshop_id is not None and employee.workshop_id != workshop_id:
            raise CrmTaskInvalid("Сотрудник не работает в выбранном цехе")
    call = db.get(CallRecord, call_id)
    if call is None:
        raise CrmTaskNotFound("Звонок не найден")
    if not call.client:
        raise CrmTaskInvalid("У звонка нет номера клиента")

    existing = db.scalar(
        select(CrmTask)
        .where(CrmTask.phone == call.client, CrmTask.status.in_(ACTIVE_STATUSES))
        .order_by(CrmTask.created_at)
    )
    if existing is not None:
        return existing, False

    now = datetime.now(UTC)
    task = CrmTask(
        phone=call.client,
        call_id=call.id,
        call_at=call.occurred_at,
        workshop_id=workshop_id,
        employee_id=employee_id,
        status=TASK_STATUS_CONTROL,
        status_changed_at=now,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(task)
    db.commit()
    # Запись в планировщике / заявка / заказ-наряд, уже появившиеся после звонка, сразу ставят
    # карточку в нужный столбец (а не «На контроле» до следующего чтения доски).
    sync_tasks(db)
    db.refresh(task)
    return task, True


# ---- автоматика ------------------------------------------------------------------


def _cutoff(task: CrmTask) -> datetime:
    """Всё, что считается «после», должно быть позже этого момента."""
    moments = [_aware(task.call_at)]
    if task.manual_moved_at is not None:
        moments.append(_aware(task.manual_moved_at))
    return max(moments)


def _take_inspection(db: Session, task: CrmTask, car: BodyCar) -> None:
    """Данные записи на осмотр на карточку: когда создана, автомобиль, клиент, даты осмотра."""
    task.inspection_at = car.created_at
    task.body_car_id = car.id
    task.car_description = car.car_description or car.plate
    task.client_name = task.client_name or car.client_name
    stages = select(func.min(BodyCarStage.start_date), func.max(BodyCarStage.end_date)).where(
        BodyCarStage.body_car_id == car.id
    )
    first, last = db.execute(stages.where(BodyCarStage.stage_name == INSPECTION_STAGE)).one()
    if first is None:  # запись создана руками с доски: этапа «Осмотр» может не быть
        first, last = db.execute(stages).one()
    task.inspection_date = first
    task.inspection_end_date = last


def _take_job(task: CrmTask, job: WorkshopJob) -> None:
    """То же для записи слесарного цеха: осмотр - день записи на пост."""
    task.inspection_at = job.created_at
    task.workshop_job_id = job.id
    task.car_description = job.car_description or job.plate
    task.client_name = task.client_name or job.client_name
    task.inspection_date = job.job_date
    task.inspection_end_date = job.job_date


def sync_tasks(db: Session) -> None:
    """Двигает активные карточки вперёд по найденным по телефону событиям. Вызывается перед
    каждым чтением доски и счётчика."""
    tasks = list(db.scalars(select(CrmTask).where(CrmTask.status.in_(ACTIVE_STATUSES))))
    if not tasks:
        return

    earliest = min(_cutoff(task) for task in tasks)
    wanted = {task.phone for task in tasks}

    # Записи кузовного цеха с этапом «Осмотр».
    cars_by_phone: dict[str, list[BodyCar]] = {}
    for car in db.scalars(
        select(BodyCar)
        .where(
            BodyCar.phone.is_not(None),
            BodyCar.created_at > earliest,
            BodyCar.id.in_(
                select(BodyCarStage.body_car_id).where(BodyCarStage.stage_name == INSPECTION_STAGE)
            ),
        )
        .order_by(BodyCar.created_at)
    ):
        for phone in set(phone_numbers(car.phone)) & wanted:
            cars_by_phone.setdefault(phone, []).append(car)

    # Заявки на ремонт и заказ-наряды: одна выборка, оба вида (заявки скрыты по умолчанию).
    created = func.coalesce(WorkOrder.created_date, WorkOrder.document_date)
    requests_by_phone: dict[str, list[WorkOrder]] = {}
    orders_by_phone: dict[str, list[WorkOrder]] = {}
    for doc in db.execute(
        select(WorkOrder)
        .where(
            WorkOrder.phone.is_not(None),
            WorkOrder.doc_type.in_((DOC_TYPE_REPAIR_REQUEST, DOC_TYPE_WORK_ORDER)),
            created > earliest,
        )
        .order_by(created),
        execution_options={"include_repair_requests": True},
    ).scalars():
        bucket = requests_by_phone if doc.doc_type == DOC_TYPE_REPAIR_REQUEST else orders_by_phone
        for phone in set(phone_numbers(doc.phone)) & wanted:
            bucket.setdefault(phone, []).append(doc)

    def first_after(docs: list[WorkOrder], moment: datetime) -> WorkOrder | None:
        return next((d for d in docs if _aware(d.created_date or d.document_date) > moment), None)

    now = datetime.now(UTC)
    changed = False
    for task in tasks:
        cutoff = _cutoff(task)
        order = first_after(orders_by_phone.get(task.phone, []), cutoff)
        if order is not None:
            task.status = TASK_STATUS_WORK_ORDER
            task.status_changed_at = now
            task.work_order_number = order.external_number
            task.client_name = task.client_name or order.customer_name
            changed = True
            continue

        if task.status == TASK_STATUS_CONTROL:
            car = next(
                (c for c in cars_by_phone.get(task.phone, []) if _aware(c.created_at) > cutoff),
                None,
            )
            if car is None:
                continue
            task.status = TASK_STATUS_INSPECTION
            task.status_changed_at = now
            _take_inspection(db, task, car)
            changed = True

        # Карточки, ставшие «Записан на осмотр» до появления связи с записью, - привязываем.
        if task.inspection_at and task.body_car_id is None and task.workshop_job_id is None:
            linked = next(
                (
                    c
                    for c in cars_by_phone.get(task.phone, [])
                    if _aware(c.created_at) == _aware(task.inspection_at)
                ),
                None,
            )
            if linked is not None:
                task.body_car_id = linked.id
                changed = True

        # Карточки, ставшие «Записан на осмотр» до появления даты осмотра, - дописываем её.
        if task.inspection_at and task.inspection_date is None and task.workshop_job_id is None:
            car = next(
                (
                    c
                    for c in cars_by_phone.get(task.phone, [])
                    if _aware(c.created_at) == _aware(task.inspection_at)
                ),
                None,
            )
            if car is not None:
                _take_inspection(db, task, car)
                changed = True

        if task.status == TASK_STATUS_INSPECTION:
            since = max(cutoff, _aware(task.inspection_at)) if task.inspection_at else cutoff
            request = first_after(requests_by_phone.get(task.phone, []), since)
            if request is not None:
                task.status = TASK_STATUS_THINKING
                task.status_changed_at = now
                task.request_number = request.external_number
                task.client_name = task.client_name or request.customer_name
                changed = True

    if changed:
        db.commit()


# ---- ручное перемещение --------------------------------------------------------------


def move_task(
    db: Session,
    task_id: uuid.UUID,
    target: str,
    *,
    reason: str | None,
    body_car_id: uuid.UUID | None = None,
    workshop_job_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    actor_name: str,
) -> CrmTask:
    task = db.get(CrmTask, task_id)
    if task is None:
        raise CrmTaskNotFound("Задача не найдена")
    if target not in TASK_STATUSES:
        raise CrmTaskInvalid("Неизвестный столбец")
    if target == task.status:
        return task
    # Руками: в «Отказ» (из любого столбца); из «Отказа» и из «Записан на осмотр» в «На контроле»;
    # из «На контроле» в «Записан на осмотр» - с записью, созданной в планировщике цеха карточки.
    # В остальные столбцы карточки приходят сами.
    back_to_control = target == TASK_STATUS_CONTROL and task.status in (
        TASK_STATUS_REFUSED,
        TASK_STATUS_INSPECTION,
    )
    to_inspection = target == TASK_STATUS_INSPECTION and task.status == TASK_STATUS_CONTROL
    if target != TASK_STATUS_REFUSED and not back_to_control and not to_inspection:
        raise CrmTaskInvalid(
            "Вручную карточку можно перенести в «Отказ», из «Отказа» и «Записан на осмотр» - "
            "в «На контроле», из «На контроле» - в «Записан на осмотр»; "
            "в остальные столбцы она переходит сама"
        )
    if to_inspection:
        _link_planner_record(db, task, body_car_id, workshop_job_id)

    reason_text = (reason or "").strip()
    if target == TASK_STATUS_REFUSED and not reason_text:
        raise CrmTaskInvalid("Укажите причину отказа")

    was_status = task.status
    now = datetime.now(UTC)
    task.status = target
    task.status_changed_at = now
    task.manual_moved_at = now
    task.moved_by_name = actor_name
    task.refuse_reason = reason_text if target == TASK_STATUS_REFUSED else None
    # Что нашла автоматика в более поздних столбцах, при переносе назад больше не верно:
    # события ищутся заново (и только после этого переноса).
    if target == TASK_STATUS_CONTROL:
        # Из «Записан на осмотр» запись планировщика удаляется; из «Отказа» её не трогаем (при
        # отказе запись остаётся), только отвязываем.
        if was_status == TASK_STATUS_INSPECTION:
            _delete_planner_record(db, task, actor_id, actor_name)
        task.body_car_id = None
        task.workshop_job_id = None
        task.inspection_at = None
        task.inspection_date = None
        task.inspection_end_date = None
        task.car_description = None
        task.request_number = None
        task.work_order_number = None
        task.next_action_date = None  # новый отсчёт: прежние планы относились к прошлому кругу
    if target == TASK_STATUS_REFUSED:
        # Причина отказа остаётся в истории комментариев и после возврата карточки назад.
        db.add(
            CrmTaskComment(
                task_id=task.id,
                status=target,
                text=f"Отказ: {reason_text}",
                author_name=actor_name,
            )
        )
    db.commit()
    db.refresh(task)
    return task


def _link_planner_record(
    db: Session,
    task: CrmTask,
    body_car_id: uuid.UUID | None,
    workshop_job_id: uuid.UUID | None,
) -> None:
    """Привязывает к карточке запись, созданную в планировщике цеха карточки (кузовной или
    слесарный), и берёт с неё данные осмотра."""
    if (body_car_id is None) == (workshop_job_id is None):
        raise CrmTaskInvalid("Создайте запись в планировщике цеха карточки")
    if body_car_id is not None:
        car = db.get(BodyCar, body_car_id)
        if car is None:
            raise CrmTaskInvalid("Запись планировщика не найдена")
        if car.workshop_id != task.workshop_id:
            raise CrmTaskInvalid("Запись создана в другом цехе")
        _take_inspection(db, task, car)
    else:
        job = db.get(WorkshopJob, workshop_job_id)
        if job is None:
            raise CrmTaskInvalid("Запись планировщика не найдена")
        if job.workshop_id != task.workshop_id:
            raise CrmTaskInvalid("Запись создана в другом цехе")
        _take_job(task, job)


def _delete_planner_record(
    db: Session, task: CrmTask, actor_id: uuid.UUID | None, actor_name: str
) -> None:
    """Удаляет запись планировщика, с которой связана карточка (если её уже не удалили)."""
    try:
        if task.body_car_id is not None and db.get(BodyCar, task.body_car_id) is not None:
            planner_service.delete_body_car(
                db, task.body_car_id, actor_user_id=actor_id, actor_name=actor_name
            )
        if task.workshop_job_id is not None and db.get(WorkshopJob, task.workshop_job_id):
            planner_service.delete_workshop_job(
                db, task.workshop_job_id, actor_user_id=actor_id, actor_name=actor_name
            )
    except planner_service.NotFoundError:
        pass


# ---- чтение --------------------------------------------------------------------------


def alert_for(task: CrmTask, warn_days: int, overdue_days: int, now: datetime) -> Alert | None:
    """Окраска карточки: только в «На контроле». Сроки идут от запланированной даты следующего
    действия (с начала этого дня по Москве), а если её нет - от перевода в столбец; пока
    запланированная дата в будущем, карточка не окрашена."""
    if task.status != TASK_STATUS_CONTROL:
        return None
    if task.next_action_date is not None:
        since = datetime.combine(task.next_action_date, time.min, tzinfo=_MSK)
    else:
        since = _aware(task.status_changed_at)
    age = now - since
    if age >= timedelta(days=overdue_days):
        return "overdue"
    if age >= timedelta(days=warn_days):
        return "warn"
    return None


def list_tasks(
    db: Session,
    *,
    workshop_id: uuid.UUID | None = None,
    employee_id: uuid.UUID | None = None,
    include_archived: bool = False,
) -> list[CrmTask]:
    """Карточки доски (после синхронизации); `workshop_id` - только этот цех. Столбцы «Отказ» и
    «Заказ-наряд» показывают только свежее (AppSettings.crm_task_archive_days дней в столбце);
    старше - архив, виден только при include_archived."""
    sync_tasks(db)
    query = select(CrmTask)
    if not include_archived:
        archive_days = get_app_settings(db).crm_task_archive_days
        archive_from = datetime.now(UTC) - timedelta(days=archive_days)
        query = query.where(
            (CrmTask.status.in_(ACTIVE_STATUSES)) | (CrmTask.status_changed_at >= archive_from)
        )
    if workshop_id is not None:
        query = query.where(CrmTask.workshop_id == workshop_id)
    if employee_id is not None:
        query = query.where(CrmTask.employee_id == employee_id)
    return list(db.scalars(query.order_by(CrmTask.status_changed_at)))


def overdue_count(db: Session, *, workshop_id: uuid.UUID | None = None) -> OverdueCount:
    sync_tasks(db)
    settings = get_app_settings(db)
    now = datetime.now(UTC)
    query = select(CrmTask).where(CrmTask.status == TASK_STATUS_CONTROL)
    if workshop_id is not None:
        query = query.where(CrmTask.workshop_id == workshop_id)
    warn = overdue = 0
    for task in db.scalars(query):
        level = alert_for(task, settings.crm_task_warn_days, settings.crm_task_overdue_days, now)
        if level is not None:
            warn += 1
        if level == "overdue":
            overdue += 1
    return OverdueCount(
        warn_count=warn,
        overdue_count=overdue,
        warn_days=settings.crm_task_warn_days,
        overdue_days=settings.crm_task_overdue_days,
    )


# ---- карточка лида: комментарии и ссылки ---------------------------------------------


def get_task(db: Session, task_id: uuid.UUID) -> CrmTask:
    task = db.get(CrmTask, task_id)
    if task is None:
        raise CrmTaskNotFound("Задача не найдена")
    return task


def add_comment(
    db: Session,
    task_id: uuid.UUID,
    text: str,
    *,
    next_action_date: date | None = None,
    actor_id: uuid.UUID | None,
    actor_name: str,
) -> CrmTaskComment:
    """Комментарий на любом этапе (в том числе в «Заказ-наряд» и «Отказ»). С датой следующего
    действия - это ещё и запланированное действие: комментарий тогда обязателен, а розовый и
    красный сроки карточки считаются от новой даты."""
    task = get_task(db, task_id)
    text = text.strip()
    if not text:
        raise CrmTaskInvalid(
            "Укажите комментарий к запланированному действию"
            if next_action_date
            else "Напишите комментарий"
        )
    comment = CrmTaskComment(
        task_id=task.id,
        status=task.status,
        text=text,
        author_id=actor_id,
        author_name=actor_name,
    )
    db.add(comment)
    if next_action_date is not None:
        db.add(
            CrmTaskAction(
                task_id=task.id,
                planned_date=next_action_date,
                comment=text,
                author_id=actor_id,
                author_name=actor_name,
            )
        )
        task.next_action_date = next_action_date
    db.commit()
    db.refresh(comment)
    return comment


def list_actions(db: Session, task_id: uuid.UUID) -> list[CrmTaskAction]:
    """История запланированных действий, новые сверху."""
    return list(
        db.scalars(
            select(CrmTaskAction)
            .where(CrmTaskAction.task_id == task_id)
            .order_by(CrmTaskAction.created_at.desc())
        )
    )


def list_comments(db: Session, task_id: uuid.UUID) -> list[CrmTaskComment]:
    """Новые сверху."""
    return list(
        db.scalars(
            select(CrmTaskComment)
            .where(CrmTaskComment.task_id == task_id)
            .order_by(CrmTaskComment.created_at.desc())
        )
    )


def comment_counts(db: Session, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not task_ids:
        return {}
    rows = db.execute(
        select(CrmTaskComment.task_id, func.count())
        .where(CrmTaskComment.task_id.in_(task_ids))
        .group_by(CrmTaskComment.task_id)
    )
    return {task_id: count for task_id, count in rows}


def linked_document_ids(db: Session, task: CrmTask) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """(id заявки на ремонт, id заказ-наряда) по номерам на карточке - для ссылок."""

    def find(number: str | None, doc_type: str) -> uuid.UUID | None:
        if not number:
            return None
        return db.scalars(
            select(WorkOrder.id)
            .where(WorkOrder.external_number == number, WorkOrder.doc_type == doc_type)
            .order_by(func.coalesce(WorkOrder.created_date, WorkOrder.document_date).desc())
            .limit(1),
            execution_options={"include_repair_requests": True},
        ).first()

    return find(task.request_number, DOC_TYPE_REPAIR_REQUEST), find(
        task.work_order_number, DOC_TYPE_WORK_ORDER
    )
