"""Контракт контроля заявок на ремонт - см. services/request_control_service.py."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class OverdueRequestOut(BaseModel):
    id: uuid.UUID
    external_number: str
    customer_name: str | None
    phone: str | None
    vehicle_description: str | None
    department: str | None
    created_at: datetime
    # "first" - просрочен первый звонок, "second" - второй.
    overdue: Literal["first", "second"]
    # Срок, который не выдержан (первого или второго звонка).
    deadline: datetime
    attempts_count: int


class OverdueRequestsResponse(BaseModel):
    # Контроль включён в настройках; выключен - список всегда пуст.
    enabled: bool
    popup_enabled: bool
    popup_interval_minutes: int
    first_count: int
    second_count: int
    items: list[OverdueRequestOut]


class AttemptOut(BaseModel):
    at: datetime
    kind: Literal["call", "manual"]
    operator: str | None
    talk_sec: int | None
    comment: str | None
    by: str | None


class RequestControlOut(BaseModel):
    id: uuid.UUID
    status: Literal["open", "converted", "disqualified", "expired"]
    overdue: Literal["first", "second"] | None
    created_at: datetime
    first_deadline: datetime
    second_deadline: datetime
    attempts_count: int
    attempts_required: int
    missed_calls: int
    attempts: list[AttemptOut]
    disqualified_at: datetime | None
    disqualified_by: str | None
    disqualify_reason: str | None
    disqualify_comment: str | None
    # Может ли именно этот пользователь дисквалифицировать заявку прямо сейчас.
    can_disqualify: bool
    # Есть ли у него право дисквалифицировать без двух попыток.
    can_disqualify_unchecked: bool
    reasons: list[str]
    min_talk_sec: int
    control_enabled: bool


class ManualAttemptIn(BaseModel):
    comment: str
    attempted_at: datetime | None = None


class DisqualifyIn(BaseModel):
    reason: str
    comment: str | None = None
