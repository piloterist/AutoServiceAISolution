"""Контракт доски задач CRM - см. services/crm_task_service.py."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

TaskStatus = Literal["control", "inspection", "thinking", "refused", "work_order"]


class CrmTaskOut(BaseModel):
    id: uuid.UUID
    phone: str
    # Откуда взята на контроль: звонок, заявка с сайта или создана руками, когда телефон нигде не
    # найден (call_at - время звонка / заявки / создания).
    source: Literal["call", "lead", "manual"] = "call"
    lead_id: uuid.UUID | None = None
    status: TaskStatus
    status_changed_at: datetime
    call_at: datetime
    workshop_id: uuid.UUID | None
    workshop_label: str | None
    employee_id: uuid.UUID | None = None
    employee_name: str | None = None
    # Запланированная дата следующего действия: от неё идут розовый / красный сроки.
    next_action_date: date | None = None
    client_name: str | None
    car_description: str | None
    request_number: str | None
    work_order_number: str | None
    refuse_reason: str | None
    # Запись на осмотр в планировщике: когда создана и на какие даты назначен осмотр.
    inspection_at: datetime | None = None
    inspection_date: date | None = None
    inspection_end_date: date | None = None
    # С карточкой связана запись планировщика: возврат в «На контроле» её удалит.
    planner_record: bool = False
    # Id записи планировщика (кузовной - BodyCar, слесарный - WorkshopJob): ссылка на неё.
    planner_record_id: uuid.UUID | None = None
    created_by_name: str
    moved_by_name: str | None
    # Окраска карточки в «На контроле»: розовая / красная (сроки - в настройках); иначе None.
    alert: Literal["warn", "overdue"] | None
    comments_count: int = 0


class CrmTaskListResponse(BaseModel):
    warn_days: int
    overdue_days: int
    items: list[CrmTaskOut]


class CrmTaskCreateIn(BaseModel):
    # Ровно одно из двух: звонок или заявка с сайта.
    call_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    # Обязателен: без цеха на контроль не взять (проверяет сервис, чтобы ответ был «Выберите цех»).
    workshop_id: uuid.UUID | None = None
    # Необязателен; обязан работать в выбранном цехе.
    employee_id: uuid.UUID | None = None


class CrmTaskManualIn(BaseModel):
    """«Создать» на доске: карточка с ручным заполнением (телефон и цех обязательны)."""

    phone: str | None = None
    workshop_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    client_name: str | None = None
    # Начальный комментарий и запланированное действие (дата + комментарий) - необязательны.
    comment: str | None = None
    action_date: date | None = None
    action_comment: str | None = None


class CrmTaskManualOut(BaseModel):
    task: CrmTaskOut
    # False - этот телефон уже на контроле, вернулась существующая карточка.
    created: bool
    # С чем связали телефон: звонок из телефонии, заявка с сайта; None - телефон нигде не найден.
    linked: Literal["call", "lead"] | None = None


class CrmTaskAssignIn(BaseModel):
    workshop_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None


class CrmTaskCreateOut(BaseModel):
    task: CrmTaskOut
    # False - этот телефон уже на контроле, вернулась существующая карточка.
    created: bool


class CrmTaskMoveIn(BaseModel):
    status: TaskStatus
    # Перенос в «Записан на осмотр»: запись, только что созданная в планировщике цеха карточки
    # (кузовной - body_car_id, слесарный - workshop_job_id).
    body_car_id: uuid.UUID | None = None
    workshop_job_id: uuid.UUID | None = None
    # Обязательна при переносе в «Отказ».
    reason: str | None = None


class CrmTaskOverdueCountOut(BaseModel):
    # Карточки «На контроле», дошедшие хотя бы до розового срока (включая красные).
    count: int
    overdue_count: int
    warn_days: int
    overdue_days: int


class CrmTaskCommentOut(BaseModel):
    id: uuid.UUID
    # Столбец, в котором была карточка, когда оставили комментарий.
    status: TaskStatus
    text: str
    author_name: str
    created_at: datetime


class CrmTaskCommentIn(BaseModel):
    text: str
    # «Запланировать действие»: дата контакта; с ней комментарий обязателен.
    next_action_date: date | None = None


class CrmTaskActionIn(BaseModel):
    planned_date: date
    comment: str


class CrmTaskActionOut(BaseModel):
    id: uuid.UUID
    planned_date: date
    comment: str
    author_name: str
    created_at: datetime


class CrmTaskLeadOut(BaseModel):
    """Заявка с сайта, с которой взята задача: поля формы, фото, откуда пришла."""

    id: uuid.UUID
    source: str
    phone: str
    name: str | None
    photos: list[str] | None
    raw_payload: dict
    request_meta: dict | None = None
    site: str | None = None
    created_at: datetime


class CrmTaskDetailOut(BaseModel):
    """Окно лида: карточка, ссылки на заявку / заказ-наряд (если найдены) и комментарии."""

    task: CrmTaskOut
    request_id: uuid.UUID | None
    work_order_id: uuid.UUID | None
    # Новые сверху.
    comments: list[CrmTaskCommentOut]
    # Заявка с сайта (если задача взята с неё), с полями формы и фото.
    lead: CrmTaskLeadOut | None = None
    # История запланированных действий, новые сверху.
    actions: list[CrmTaskActionOut] = []
