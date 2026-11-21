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

import re
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
from app.models.department import Department
from app.models.employee import Employee
from app.models.website_lead import WebsiteLead
from app.models.work_order import DOC_TYPE_REPAIR_REQUEST, DOC_TYPE_WORK_ORDER, WorkOrder
from app.models.workshop import Workshop
from app.models.workshop_job import WorkshopJob
from app.services import audit_log_service, planner_service
from app.services.request_control_service import _aware
from app.services.request_control_service import _phones as phone_numbers
from app.services.settings_service import get_app_settings

_MSK = timezone(timedelta(hours=3))
INSPECTION_STAGE = "Осмотр"
# Статус заказ-наряда в 1С, при котором он не считается (клиент отказался): WorkOrder.status.
REFUSED_ORDER_STATUS = "отказ"
# Карточки, за которыми ещё следит автоматика.
ACTIVE_STATUSES = (TASK_STATUS_CONTROL, TASK_STATUS_INSPECTION, TASK_STATUS_THINKING)

Alert = Literal["warn", "overdue"]

# Журнал (Настройки -> Логи, schedule_audit_log): всё, что происходит с карточкой, - создание,
# переходы по столбцам (руками и автоматически), комментарии, запланированные действия.
LOG_ENTITY = "crm_task"
SYSTEM_ACTOR = "Система (автоматически)"
STATUS_TITLES = {
    TASK_STATUS_CONTROL: "На контроле",
    TASK_STATUS_INSPECTION: "Записан на осмотр",
    TASK_STATUS_THINKING: "Думает",
    TASK_STATUS_REFUSED: "Отказ",
    TASK_STATUS_WORK_ORDER: "Заказ-наряд",
}


def _fmt_date(value: date | None) -> str | None:
    return value.strftime("%d.%m.%Y") if value else None


def _fmt_phone(phone: str) -> str:
    if len(phone) == 10:
        return f"+7 {phone[:3]} {phone[3:6]}-{phone[6:8]}-{phone[8:]}"
    return phone


def _log(
    db: Session,
    task: CrmTask,
    changes: dict,
    *,
    action: str = "update",
    actor_id: uuid.UUID | None,
    actor_name: str,
) -> None:
    """Запись в журнал (без commit - его делает вызывающий). Пустое изменение не пишется."""
    if not changes:
        return
    context = _fmt_phone(task.phone) + (f" · {task.client_name}" if task.client_name else "")
    audit_log_service.record_change(
        db,
        entity_type=LOG_ENTITY,
        entity_id=task.id,
        action=action,
        changes=changes,
        actor_user_id=actor_id,
        actor_name=actor_name,
        car_description=context,
    )


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


def _check_assignment(
    db: Session, workshop_id: uuid.UUID | None, employee_id: uuid.UUID | None
) -> Employee | None:
    """Цех обязателен (по нему карточка попадает в фильтр доски и в счётчик планировщика);
    сотрудник - из этого цеха или без цеха в справочнике."""
    if workshop_id is None:
        raise CrmTaskInvalid("Выберите цех")
    if db.get(Workshop, workshop_id) is None:
        raise CrmTaskInvalid("Цех не найден")
    if employee_id is None:
        return None
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise CrmTaskInvalid("Сотрудник не найден")
    # Сотрудник без цеха (в справочнике цех не указан) подходит к любому цеху.
    if employee.workshop_id is not None and employee.workshop_id != workshop_id:
        raise CrmTaskInvalid("Сотрудник не работает в выбранном цехе")
    return employee


def _open_task(
    db: Session,
    *,
    phone: str,
    at: datetime,
    call_id: uuid.UUID | None,
    lead_id: uuid.UUID | None,
    client_name: str | None,
    kind: str,
    workshop_id: uuid.UUID,
    employee: Employee | None,
    actor_id: uuid.UUID | None,
    actor_name: str,
) -> tuple[CrmTask, bool]:
    """Одна карточка на телефон: если он уже ведётся (карточка не в «Отказе» и не в «Заказ-наряде»),
    возвращает её (created=False). Иначе создаёт в «На контроле»; запись в планировщике, заявка или
    заказ-наряд, уже появившиеся после звонка / заявки, сразу ставят её в нужный столбец."""
    existing = db.scalar(
        select(CrmTask)
        .where(CrmTask.phone == phone, CrmTask.status.in_(ACTIVE_STATUSES))
        .order_by(CrmTask.created_at)
    )
    if existing is not None:
        return existing, False

    now = datetime.now(UTC)
    task = CrmTask(
        phone=phone,
        call_id=call_id,
        lead_id=lead_id,
        call_at=at,
        client_name=client_name,
        workshop_id=workshop_id,
        employee_id=employee.id if employee else None,
        status=TASK_STATUS_CONTROL,
        status_changed_at=now,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(task)
    db.flush()
    workshop = db.get(Workshop, workshop_id)
    department = db.get(Department, workshop.department_id) if workshop else None
    created = {
        "phone": _fmt_phone(phone),
        "task_source": kind,
        "workshop_label": f"{department.name if department else '?'} — {workshop.workshop_type}",
        "employee_name": employee.full_name if employee else None,
        "status": STATUS_TITLES[TASK_STATUS_CONTROL],
    }
    _log(
        db,
        task,
        {key: {"old": None, "new": value} for key, value in created.items() if value},
        action="create",
        actor_id=actor_id,
        actor_name=actor_name,
    )
    db.commit()
    sync_tasks(db)
    db.refresh(task)
    return task, True


def create_from_call(
    db: Session,
    call_id: uuid.UUID,
    *,
    workshop_id: uuid.UUID | None,
    employee_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None,
    actor_name: str,
) -> tuple[CrmTask, bool]:
    """Берёт телефон звонка на контроль в выбранном цехе."""
    employee = _check_assignment(db, workshop_id, employee_id)
    call = db.get(CallRecord, call_id)
    if call is None:
        raise CrmTaskNotFound("Звонок не найден")
    if not call.client:
        raise CrmTaskInvalid("У звонка нет номера клиента")
    return _open_task(
        db,
        phone=call.client,
        at=call.occurred_at,
        call_id=call.id,
        lead_id=None,
        client_name=None,
        kind="Звонок",
        workshop_id=workshop_id,
        employee=employee,
        actor_id=actor_id,
        actor_name=actor_name,
    )


def create_from_lead(
    db: Session,
    lead_id: uuid.UUID,
    *,
    workshop_id: uuid.UUID | None,
    employee_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None,
    actor_name: str,
) -> tuple[CrmTask, bool]:
    """Берёт телефон заявки с сайта на контроль. Время заявки - точка отсчёта (как время звонка):
    заказ-наряд, заявка на ремонт и запись в планировщике ищутся позже него."""
    employee = _check_assignment(db, workshop_id, employee_id)
    lead = db.get(WebsiteLead, lead_id)
    if lead is None:
        raise CrmTaskNotFound("Заявка не найдена")
    return _open_task(
        db,
        phone=lead.phone,
        at=lead.created_at,
        call_id=None,
        lead_id=lead.id,
        client_name=lead.name,
        kind="Заявка с сайта",
        workshop_id=workshop_id,
        employee=employee,
        actor_id=actor_id,
        actor_name=actor_name,
    )


def manual_phone(raw: str | None) -> str:
    """Телефон, введённый руками: последние 10 цифр, как в telephony_calls.client."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        raise CrmTaskInvalid("Укажите телефон")
    if len(digits) < 10:
        raise CrmTaskInvalid("Телефон должен содержать не меньше 10 цифр")
    return digits[-10:]


def create_manual(
    db: Session,
    *,
    phone: str | None,
    workshop_id: uuid.UUID | None,
    employee_id: uuid.UUID | None = None,
    client_name: str | None = None,
    comment: str | None = None,
    action_date: date | None = None,
    action_comment: str | None = None,
    actor_id: uuid.UUID | None,
    actor_name: str,
) -> tuple[CrmTask, bool, Literal["call", "lead"] | None]:
    """Карточка, созданная руками на доске («Создать»). Телефон ищется в телефонии и среди заявок с
    сайта: найден - карточка связывается с самым свежим звонком или заявкой (по телефону они сразу
    получают статус задачи, а время звонка / заявки становится точкой отсчёта автоматики, как при
    «На контроль» у звонка); не найден - точка отсчёта момент создания. Телефон уже ведётся -
    вернётся существующая карточка (created=False), комментарий и действие в неё не добавляются.
    Возвращает (карточка, создана ли, с чем связана)."""
    key = manual_phone(phone)
    employee = _check_assignment(db, workshop_id, employee_id)
    comment = (comment or "").strip()
    action_comment = (action_comment or "").strip()
    if action_date is not None and not action_comment:
        raise CrmTaskInvalid("Укажите комментарий к запланированному действию")
    if action_comment and action_date is None:
        raise CrmTaskInvalid("Укажите дату запланированного действия")

    call = db.scalar(
        select(CallRecord).where(CallRecord.client == key).order_by(CallRecord.occurred_at.desc())
    )
    lead = db.scalar(
        select(WebsiteLead).where(WebsiteLead.phone == key).order_by(WebsiteLead.created_at.desc())
    )
    if call is not None and (lead is None or call.occurred_at >= lead.created_at):
        link, at, call_id, lead_id, lead_name = "call", call.occurred_at, call.id, None, None
    elif lead is not None:
        link, at, call_id, lead_id, lead_name = "lead", lead.created_at, None, lead.id, lead.name
    else:
        link, at, call_id, lead_id, lead_name = None, datetime.now(UTC), None, None, None

    task, created = _open_task(
        db,
        phone=key,
        at=at,
        call_id=call_id,
        lead_id=lead_id,
        client_name=(client_name or "").strip() or lead_name,
        kind="Вручную" if link is None else f"Вручную ({'звонок' if link == 'call' else 'заявка'})",
        workshop_id=workshop_id,
        employee=employee,
        actor_id=actor_id,
        actor_name=actor_name,
    )
    if created:
        if comment:
            add_comment(db, task.id, comment, actor_id=actor_id, actor_name=actor_name)
        if action_date is not None:
            add_comment(
                db,
                task.id,
                action_comment,
                next_action_date=action_date,
                actor_id=actor_id,
                actor_name=actor_name,
            )
        db.refresh(task)
    return task, created, link


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
    earliest_call = min(_aware(task.call_at) for task in tasks)
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
            created > earliest_call,
        )
        .order_by(created),
        execution_options={"include_repair_requests": True},
    ).scalars():
        if (doc.status or "").strip().lower() == REFUSED_ORDER_STATUS:
            continue  # заказ-наряд в статусе «Отказ» в цепочку не входит
        bucket = requests_by_phone if doc.doc_type == DOC_TYPE_REPAIR_REQUEST else orders_by_phone
        for phone in set(phone_numbers(doc.phone)) & wanted:
            bucket.setdefault(phone, []).append(doc)

    def first_after(docs: list[WorkOrder], moment: datetime) -> WorkOrder | None:
        return next((d for d in docs if _aware(d.created_date or d.document_date) > moment), None)

    now = datetime.now(UTC)
    changed = False
    before = {task.id: task.status for task in tasks}
    for task in tasks:
        cutoff = _cutoff(task)
        # Заказ-наряд сравнивается только со временем звонка, а не с ручными перемещениями: они
        # приходят из 1С с задержкой (иногда после того, как карточку уже двигали руками).
        order = first_after(orders_by_phone.get(task.phone, []), _aware(task.call_at))
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
            # Как и заказ-наряд, заявка на ремонт сравнивается только со временем звонка: её могли
            # создать до записи на осмотр, и выгружается она из 1С с задержкой.
            request = first_after(requests_by_phone.get(task.phone, []), _aware(task.call_at))
            if request is not None:
                task.status = TASK_STATUS_THINKING
                task.status_changed_at = now
                task.request_number = request.external_number
                task.client_name = task.client_name or request.customer_name
                changed = True

    for task in tasks:
        if task.status == before[task.id]:
            continue
        found = {
            "status": {"old": STATUS_TITLES[before[task.id]], "new": STATUS_TITLES[task.status]}
        }
        if task.status == TASK_STATUS_INSPECTION:
            found["inspection_date"] = {"old": None, "new": _fmt_date(task.inspection_date)}
        if task.request_number and task.status == TASK_STATUS_THINKING:
            found["request_number"] = {"old": None, "new": task.request_number}
        if task.work_order_number and task.status == TASK_STATUS_WORK_ORDER:
            found["work_order_number"] = {"old": None, "new": task.work_order_number}
        _log(db, task, found, actor_id=None, actor_name=SYSTEM_ACTOR)
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
    had_record = task.body_car_id is not None or task.workshop_job_id is not None
    old_next_action = task.next_action_date
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
    moved = {"status": {"old": STATUS_TITLES[was_status], "new": STATUS_TITLES[target]}}
    if target == TASK_STATUS_REFUSED:
        moved["refuse_reason"] = {"old": None, "new": reason_text}
    if to_inspection:
        moved["inspection_date"] = {"old": None, "new": _fmt_date(task.inspection_date)}
        moved["planner_record"] = {"old": None, "new": "создана в планировщике"}
    if back_to_control:
        if was_status == TASK_STATUS_INSPECTION and had_record:
            moved["planner_record"] = {"old": "запись в планировщике", "new": "удалена"}
        if old_next_action is not None:
            moved["planned_date"] = {"old": _fmt_date(old_next_action), "new": None}
    _log(db, task, moved, actor_id=actor_id, actor_name=actor_name)
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
    """Окраска карточки: только в «На контроле».

    Без запланированного действия: розовая через warn_days дней после перевода в столбец, красная
    через overdue_days. С запланированным действием: розовая уже с начала запланированного дня (по
    Москве) - пора действовать, красная - позже на тот же промежуток (overdue_days - warn_days),
    что и без плана. До запланированного дня карточка не окрашена."""
    if task.status != TASK_STATUS_CONTROL:
        return None
    if task.next_action_date is not None:
        planned = datetime.combine(task.next_action_date, time.min, tzinfo=_MSK)
        if now < planned:
            return None
        if (
            now - planned >= timedelta(days=max(overdue_days - warn_days, 0))
            and overdue_days > warn_days
        ):
            return "overdue"
        return "warn"
    age = now - _aware(task.status_changed_at)
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
    previous_plan = task.next_action_date
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
    logged = {"comment": {"old": None, "new": text}}
    if next_action_date is not None:
        logged["planned_date"] = {
            "old": _fmt_date(previous_plan),
            "new": _fmt_date(next_action_date),
        }
    _log(db, task, logged, actor_id=actor_id, actor_name=actor_name)
    db.commit()
    db.refresh(comment)
    return comment


def update_assignment(
    db: Session,
    task_id: uuid.UUID,
    *,
    workshop_id: uuid.UUID | None,
    employee_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    actor_name: str,
) -> CrmTask:
    """Меняет цех и сотрудника карточки (правила те же, что при взятии на контроль: цех обязателен,
    сотрудник - из этого цеха или без цеха в справочнике). Карточку с записью в планировщике
    перенести в другой цех нельзя: запись осталась бы в прежнем."""
    task = get_task(db, task_id)
    if workshop_id is None:
        raise CrmTaskInvalid("Выберите цех")
    workshop = db.get(Workshop, workshop_id)
    if workshop is None:
        raise CrmTaskInvalid("Цех не найден")
    employee = None
    if employee_id is not None:
        employee = db.get(Employee, employee_id)
        if employee is None:
            raise CrmTaskInvalid("Сотрудник не найден")
        if employee.workshop_id is not None and employee.workshop_id != workshop_id:
            raise CrmTaskInvalid("Сотрудник не работает в выбранном цехе")
    if workshop_id != task.workshop_id and (
        task.body_car_id is not None or task.workshop_job_id is not None
    ):
        raise CrmTaskInvalid(
            "У карточки есть запись в планировщике прежнего цеха: сначала верните её "
            "в «На контроле» (запись удалится) или оставьте цех"
        )

    def label(shop_id: uuid.UUID | None) -> str | None:
        shop = db.get(Workshop, shop_id) if shop_id else None
        department = db.get(Department, shop.department_id) if shop else None
        return f"{department.name if department else '?'} — {shop.workshop_type}" if shop else None

    def person(emp_id: uuid.UUID | None) -> str | None:
        emp = db.get(Employee, emp_id) if emp_id else None
        return emp.full_name if emp else None

    changes: dict = {}
    if workshop_id != task.workshop_id:
        changes["workshop_label"] = {"old": label(task.workshop_id), "new": label(workshop_id)}
    if employee_id != task.employee_id:
        changes["employee_name"] = {"old": person(task.employee_id), "new": person(employee_id)}
    task.workshop_id = workshop_id
    task.employee_id = employee.id if employee else None
    _log(db, task, changes, actor_id=actor_id, actor_name=actor_name)
    db.commit()
    db.refresh(task)
    return task


def _sync_next_action(db: Session, task: CrmTask) -> None:
    """Действует последнее созданное запланированное действие; нет ни одного - плана нет."""
    latest = db.scalar(
        select(CrmTaskAction)
        .where(CrmTaskAction.task_id == task.id)
        .order_by(CrmTaskAction.created_at.desc())
    )
    task.next_action_date = latest.planned_date if latest is not None else None


def _get_action(db: Session, task_id: uuid.UUID, action_id: uuid.UUID) -> CrmTaskAction:
    action = db.get(CrmTaskAction, action_id)
    if action is None or action.task_id != task_id:
        raise CrmTaskNotFound("Запланированное действие не найдено")
    return action


def update_action(
    db: Session,
    task_id: uuid.UUID,
    action_id: uuid.UUID,
    *,
    planned_date: date,
    comment: str,
    actor_id: uuid.UUID | None = None,
    actor_name: str = "Неизвестно",
) -> CrmTaskAction:
    """Меняет дату и комментарий запланированного действия; окраска считается от новой даты, если
    это действующее (последнее) действие. Запись в истории комментариев остаётся как была."""
    task = get_task(db, task_id)
    action = _get_action(db, task_id, action_id)
    comment = comment.strip()
    if not comment:
        raise CrmTaskInvalid("Укажите комментарий к запланированному действию")
    edits = {}
    if action.planned_date != planned_date:
        edits["planned_date"] = {
            "old": _fmt_date(action.planned_date),
            "new": _fmt_date(planned_date),
        }
    if action.comment != comment:
        edits["comment"] = {"old": action.comment, "new": comment}
    action.planned_date = planned_date
    action.comment = comment
    db.flush()
    _sync_next_action(db, task)
    _log(db, task, edits, actor_id=actor_id, actor_name=actor_name)
    db.commit()
    db.refresh(action)
    return action


def delete_action(
    db: Session,
    task_id: uuid.UUID,
    action_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
    actor_name: str = "Неизвестно",
) -> None:
    """Удаляет запланированное действие; действующим становится предыдущее, а если его нет -
    сроки снова считаются от перевода в столбец."""
    task = get_task(db, task_id)
    action = _get_action(db, task_id, action_id)
    removed = {
        "planned_date": {"old": _fmt_date(action.planned_date), "new": None},
        "comment": {"old": action.comment, "new": None},
    }
    db.delete(action)
    db.flush()
    _sync_next_action(db, task)
    _log(db, task, removed, actor_id=actor_id, actor_name=actor_name)
    db.commit()


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
