"""Контроль заявок на ремонт (product ask, 2026-11-06).

Заявка на ремонт (1C: «Заявка на ремонт», WorkOrder.doc_type = "repair_request") создаётся
на цех после заезда клиента. Она не должна повиснуть: пока по ней нет заказ-наряда, клиенту
надо дозвониться и поговорить - дважды, в сроки из настроек. Заявка закрывается одним из
трёх способов: по ней появился заказ-наряд (WorkOrder.linked_work_orders), её дисквалифицировали
вручную, либо она устарела (старше request_auto_disqualify_days, дисквалифицируется сама -
вычисляется на лету, ничего не пишется).

Попытка - состоявшийся разговор, а не звонок:
  - исходящий, отвеченный звонок на номер клиента из заявки, от request_min_talk_sec секунд
    разговора, после создания заявки. Линия и сотрудник неважны (цех не учитывается:
    клиента могли передать); недозвон попыткой не считается;
  - либо ручная отметка (RepairRequestAttempt) с обязательным комментарием.
Попытки считаются по календарным дням (МСК): два разговора в один день - одна попытка.

Просрочка (в «Ошибках» и на колокольчике планировщика), сроки считаются от создания заявки:
  - «первый звонок»: попыток нет, а request_first_call_days уже прошли;
  - «второй звонок»: попытка одна, а request_second_call_days уже прошли.
Она не хранится, а вычисляется при каждом чтении, поэтому сама исчезает, как только причина
устранена (дозвонились, появился заказ-наряд, заявку дисквалифицировали).

Дисквалифицировать вручную можно только при двух попытках; без них - только роли с правом
«Дисквалификация заявок без попыток» (RoleTabVisibility.request_disqualify_unchecked, у Админа
оно есть всегда).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings
from app.models.call_record import CALL_TYPE_OUT, CallRecord
from app.models.repair_request_attempt import RepairRequestAttempt
from app.models.role_tab_visibility import RoleTabVisibility
from app.models.user import ROLE_ADMIN, User
from app.models.work_order import DOC_TYPE_REPAIR_REQUEST, WorkOrder
from app.models.workshop import Workshop
from app.models.workshop_source_department import WorkshopSourceDepartment
from app.services.settings_service import get_app_settings

SHOP_TZ = ZoneInfo("Europe/Moscow")

STATUS_OPEN = "open"
STATUS_CONVERTED = "converted"
STATUS_DISQUALIFIED = "disqualified"
STATUS_EXPIRED = "expired"
RequestStatus = Literal["open", "converted", "disqualified", "expired"]

OVERDUE_FIRST = "first"
OVERDUE_SECOND = "second"
Overdue = Literal["first", "second"]

ATTEMPTS_REQUIRED = 2
REASON_OTHER = "Другое"
# Причины дисквалификации. Закрытый список в коде (как роли и типы цехов);
# «Другое» требует комментария.
DISQUALIFY_REASONS = (
    "Отказ клиента",
    "Дорого",
    "Уехал в другой сервис",
    "Ошибочная заявка",
    "Не удалось связаться",
    REASON_OTHER,
)
AUTO_REASON = "Устарела"


class RequestControlError(Exception):
    """Base class - the endpoint maps each subclass to an HTTP status."""


class RequestNotFound(RequestControlError):
    pass


class RequestNotOpen(RequestControlError):
    pass


class RequestForbidden(RequestControlError):
    pass


class RequestInvalid(RequestControlError):
    pass


@dataclass
class Attempt:
    at: datetime
    kind: Literal["call", "manual"]
    # call: who dialled (extension) and for how long; manual: who marked it and the comment.
    operator: str | None = None
    talk_sec: int | None = None
    comment: str | None = None
    by: str | None = None


@dataclass
class RequestState:
    request: WorkOrder
    status: RequestStatus
    created_at: datetime
    first_deadline: datetime
    second_deadline: datetime
    attempts: list[Attempt] = field(default_factory=list)
    attempts_count: int = 0  # засчитанные: по календарным дням
    missed_calls: int = 0  # исходящие без разговора - справочно, не попытки
    overdue: Overdue | None = None


# ---- helpers ---------------------------------------------------------------


def _created_at(request: WorkOrder) -> datetime:
    """Когда заявка заведена: ДатаСоздания, а если её нет - дата документа."""
    return request.created_date or request.document_date


def _created_expr():
    return func.coalesce(WorkOrder.created_date, WorkOrder.document_date)


def _phones(value: str | None) -> list[str]:
    """Номера клиента из WorkOrder.phone (сырой текст 1С, бывает несколько через , ; /) -
    последние 10 цифр, как в telephony_calls.client."""
    result: list[str] = []
    for part in re.split(r"[,;/\n]", value or ""):
        digits = re.sub(r"\D", "", part)
        if len(digits) >= 10:
            result.append(digits[-10:])
    return result


def _msk_day(moment: datetime) -> date:
    return moment.astimezone(SHOP_TZ).date()


def _has_no_work_order(request: WorkOrder) -> bool:
    return not request.linked_work_orders


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


# ---- state -------------------------------------------------------------------


def _build_states(
    db: Session, requests: list[WorkOrder], settings: AppSettings, now: datetime
) -> dict[uuid.UUID, RequestState]:
    """Состояние каждой заявки: статус, попытки, просрочка. Звонки и ручные отметки
    читаются один раз на весь набор заявок."""
    if not requests:
        return {}

    phones = {phone for request in requests for phone in _phones(request.phone)}
    calls_by_phone: dict[str, list[CallRecord]] = {}
    if phones:
        earliest = min(_aware(_created_at(request)) for request in requests)
        for call in db.scalars(
            select(CallRecord)
            .where(
                CallRecord.client.in_(phones),
                CallRecord.call_type == CALL_TYPE_OUT,
                CallRecord.occurred_at > earliest,
            )
            .order_by(CallRecord.occurred_at)
        ):
            calls_by_phone.setdefault(call.client or "", []).append(call)

    manual_by_request: dict[uuid.UUID, list[RepairRequestAttempt]] = {}
    for manual in db.scalars(
        select(RepairRequestAttempt)
        .where(RepairRequestAttempt.work_order_id.in_([r.id for r in requests]))
        .order_by(RepairRequestAttempt.attempted_at)
    ):
        manual_by_request.setdefault(manual.work_order_id, []).append(manual)

    states: dict[uuid.UUID, RequestState] = {}
    for request in requests:
        created = _aware(_created_at(request))
        state = RequestState(
            request=request,
            status=STATUS_OPEN,
            created_at=created,
            first_deadline=created + timedelta(days=settings.request_first_call_days),
            second_deadline=created + timedelta(days=settings.request_second_call_days),
        )
        if not _has_no_work_order(request):
            state.status = STATUS_CONVERTED
        elif request.request_disqualified_at is not None:
            state.status = STATUS_DISQUALIFIED
        elif now - created > timedelta(days=settings.request_auto_disqualify_days):
            state.status = STATUS_EXPIRED

        seen_calls: set[uuid.UUID] = set()
        for phone in _phones(request.phone):
            for call in calls_by_phone.get(phone, []):
                if call.id in seen_calls or _aware(call.occurred_at) <= created:
                    continue
                seen_calls.add(call.id)
                if call.answered and call.talk_sec >= settings.request_min_talk_sec:
                    state.attempts.append(
                        Attempt(
                            at=call.occurred_at,
                            kind="call",
                            operator=call.operator,
                            talk_sec=call.talk_sec,
                        )
                    )
                else:
                    state.missed_calls += 1
        for manual in manual_by_request.get(request.id, []):
            state.attempts.append(
                Attempt(
                    at=manual.attempted_at,
                    kind="manual",
                    comment=manual.comment,
                    by=manual.created_by_name,
                )
            )
        state.attempts.sort(key=lambda attempt: attempt.at)
        state.attempts_count = len({_msk_day(attempt.at) for attempt in state.attempts})

        if state.status == STATUS_OPEN:
            if state.attempts_count == 0 and now > state.first_deadline:
                state.overdue = OVERDUE_FIRST
            elif state.attempts_count == 1 and now > state.second_deadline:
                state.overdue = OVERDUE_SECOND
        states[request.id] = state
    return states


def _candidate_requests_query(settings: AppSettings, now: datetime):
    """Заявки, которые вообще могут быть просрочены: без заказ-наряда, не дисквалифицированы,
    не устарели, и срок первого звонка уже вышел."""
    created = _created_expr()
    return select(WorkOrder).where(
        WorkOrder.doc_type == DOC_TYPE_REPAIR_REQUEST,
        or_(WorkOrder.linked_work_orders.is_(None), WorkOrder.linked_work_orders == ""),
        WorkOrder.request_disqualified_at.is_(None),
        created >= now - timedelta(days=settings.request_auto_disqualify_days),
        created < now - timedelta(days=settings.request_first_call_days),
    )


def overdue_states(
    db: Session,
    *,
    departments: list[str] | None = None,
    now: datetime | None = None,
) -> list[RequestState]:
    """Просроченные заявки (самые давние первыми). `departments` - сырые WorkOrder.department
    цеха пользователя; None = все цеха. Пусто, если контроль выключен."""
    settings = get_app_settings(db)
    if not settings.request_control_enabled:
        return []
    now = now or datetime.now(UTC)
    query = _candidate_requests_query(settings, now)
    if departments is not None:
        query = query.where(WorkOrder.department.in_(departments))
    requests = list(
        db.execute(
            query.order_by(_created_expr()), execution_options={"include_repair_requests": True}
        ).scalars()
    )
    states = _build_states(db, requests, settings, now)
    return [state for state in states.values() if state.overdue is not None]


def overdue_for_items(
    db: Session, items: list[WorkOrder], *, now: datetime | None = None
) -> dict[uuid.UUID, Overdue]:
    """Просрочка для страницы списка заказ-нарядов: id заявки -> вид просрочки (только
    просроченные). Звонки читаются лишь для заявок-кандидатов."""
    settings = get_app_settings(db)
    if not settings.request_control_enabled:
        return {}
    now = now or datetime.now(UTC)
    created_from = now - timedelta(days=settings.request_auto_disqualify_days)
    created_to = now - timedelta(days=settings.request_first_call_days)
    candidates = [
        item
        for item in items
        if item.doc_type == DOC_TYPE_REPAIR_REQUEST
        and _has_no_work_order(item)
        and item.request_disqualified_at is None
        and created_from <= _aware(_created_at(item)) < created_to
    ]
    states = _build_states(db, candidates, settings, now)
    return {request_id: state.overdue for request_id, state in states.items() if state.overdue}


# ---- scope: whose цех -------------------------------------------------------


def departments_for_user(db: Session, user_id: uuid.UUID | None) -> list[str] | None:
    """Сырые WorkOrder.department цеха пользователя; None = без ограничения (все цеха):
    нет пользователя, роль со всеми подразделениями, либо у него не задан ни цех,
    ни подразделение."""
    user = db.get(User, user_id) if user_id else None
    if user is None:
        return None
    role_row = db.scalar(select(RoleTabVisibility).where(RoleTabVisibility.role == user.role))
    if role_row is not None and role_row.all_departments:
        return None
    if user.workshop_id is not None:
        workshop_ids = [user.workshop_id]
    elif user.department_id is not None:
        workshop_ids = list(
            db.scalars(select(Workshop.id).where(Workshop.department_id == user.department_id))
        )
    else:
        return None
    return list(
        db.scalars(
            select(WorkshopSourceDepartment.source_department).where(
                WorkshopSourceDepartment.workshop_id.in_(workshop_ids)
            )
        )
    )


def departments_for_workshop(
    db: Session, user_id: uuid.UUID | None, workshop_id: uuid.UUID
) -> list[str]:
    """Сырые WorkOrder.department конкретного цеха планировщика (Каховка/Слесарный и т.п.),
    суженные до цеха пользователя, если он ограничен. Цех без привязанных подразделений
    даёт пустой список, то есть заявок в нём нет."""
    shop = list(
        db.scalars(
            select(WorkshopSourceDepartment.source_department).where(
                WorkshopSourceDepartment.workshop_id == workshop_id
            )
        )
    )
    mine = departments_for_user(db, user_id)
    if mine is None:
        return shop
    allowed = set(mine)
    return [department for department in shop if department in allowed]


def can_disqualify_unchecked(db: Session, user_id: uuid.UUID | None) -> bool:
    user = db.get(User, user_id) if user_id else None
    if user is None:
        return False
    if user.role == ROLE_ADMIN:
        return True
    role_row = db.scalar(select(RoleTabVisibility).where(RoleTabVisibility.role == user.role))
    return role_row is not None and role_row.request_disqualify_unchecked


# ---- one request -------------------------------------------------------------


def _get_request(db: Session, request_id: uuid.UUID) -> WorkOrder:
    request = db.execute(
        select(WorkOrder).where(WorkOrder.id == request_id),
        execution_options={"include_repair_requests": True},
    ).scalar_one_or_none()
    if request is None or request.doc_type != DOC_TYPE_REPAIR_REQUEST:
        raise RequestNotFound(str(request_id))
    return request


def get_state(db: Session, request_id: uuid.UUID, *, now: datetime | None = None) -> RequestState:
    request = _get_request(db, request_id)
    settings = get_app_settings(db)
    return _build_states(db, [request], settings, now or datetime.now(UTC))[request.id]


def add_manual_attempt(
    db: Session,
    request_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None,
    user_name: str,
    comment: str,
    attempted_at: datetime | None = None,
    now: datetime | None = None,
) -> RequestState:
    """Ручная отметка попытки (написали в мессенджер, клиент зашёл лично...)."""
    now = now or datetime.now(UTC)
    comment = (comment or "").strip()
    if not comment:
        raise RequestInvalid("Комментарий обязателен: по нему отметку можно проверить")
    state = get_state(db, request_id, now=now)
    if state.status != STATUS_OPEN:
        raise RequestNotOpen("По этой заявке попытки уже не отмечаются")
    moment = _aware(attempted_at) if attempted_at else now
    if moment > now + timedelta(minutes=5):
        raise RequestInvalid("Время попытки не может быть в будущем")
    db.add(
        RepairRequestAttempt(
            work_order_id=request_id,
            attempted_at=moment,
            comment=comment,
            created_by_id=user_id,
            created_by_name=user_name,
        )
    )
    db.commit()
    return get_state(db, request_id, now=now)


def disqualify(
    db: Session,
    request_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None,
    user_name: str,
    reason: str,
    comment: str | None,
    now: datetime | None = None,
) -> RequestState:
    now = now or datetime.now(UTC)
    if reason not in DISQUALIFY_REASONS:
        raise RequestInvalid("Выберите причину из списка")
    comment = (comment or "").strip() or None
    if reason == REASON_OTHER and comment is None:
        raise RequestInvalid("Для причины «Другое» нужен комментарий")
    state = get_state(db, request_id, now=now)
    if state.status != STATUS_OPEN:
        raise RequestNotOpen(
            "Заявка уже закрыта: по ней есть заказ-наряд или она дисквалифицирована"
        )
    if state.attempts_count < ATTEMPTS_REQUIRED and not can_disqualify_unchecked(db, user_id):
        raise RequestForbidden(
            "Дисквалифицировать можно после двух попыток связаться с клиентом "
            "(в разные дни). Без них - только управляющий"
        )
    request = state.request
    request.request_disqualified_at = now
    request.request_disqualified_by = user_name
    request.request_disqualify_reason = reason
    request.request_disqualify_comment = comment
    db.commit()
    return get_state(db, request_id, now=now)
