"""Pydantic schemas for the Боксы page and the on-site video-control node - see
services/bay_service.py."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.bay import EVENT_TYPES

BayState = Literal["free", "occupied", "review"]
BayKind = Literal["bay", "gate"]


class BayEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    occurred_at: datetime
    plate: str | None
    ocr_confidence: Decimal | None
    has_snapshot: bool
    review_status: str
    source: str
    note: str | None


class BayCardOut(BaseModel):
    id: uuid.UUID
    workshop_id: uuid.UUID
    name: str
    camera_code: str | None
    enabled: bool
    # "gate" - ворота кузовного цеха (много машин внутри, см. GateStayOut), inside_count - сколько
    # машин сейчас в цеху; у обычного бокса kind="bay", inside_count=0.
    kind: BayKind = "bay"
    inside_count: int = 0
    state: BayState
    plate: str | None
    occupied_since: datetime | None
    # Заказ-наряд, привязанный в момент въезда машины, которая сейчас в боксе.
    work_order_id: uuid.UUID | None
    work_order_number: str | None
    # Рабочие часы цеха (узел шлёт кадр раз в минуту только в них): "HH:MM:SS", дни 0=пн..6=вс.
    work_start: str | None
    work_end: str | None
    work_days: list[int]
    # Связь с узлом на площадке: когда он выходил на связь в последний раз, отдаёт ли камера
    # видео и с какого момента (None, если узел по этой камере ещё не отчитывался).
    node_seen_at: datetime | None
    camera_ok: bool | None
    camera_ok_since: datetime | None
    # Когда снят последний кадр бокса (узел шлёт раз в минуту), иначе None.
    latest_frame_at: datetime | None
    last_entry: BayEventOut | None
    last_exit: BayEventOut | None


class BaysResponse(BaseModel):
    bays: list[BayCardOut]


class BayCreate(BaseModel):
    workshop_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    camera_code: str | None = Field(default=None, max_length=50)
    kind: BayKind = "bay"


class BayUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    camera_code: str | None = Field(default=None, max_length=50)
    enabled: bool | None = None


class BayEventCreate(BaseModel):
    """One event from the on-site node or typed in by hand on the page."""

    event_type: str
    plate: str | None = Field(default=None, max_length=20)
    ocr_confidence: Decimal | None = Field(default=None, ge=0, le=1)
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)
    # JPEG, base64 (no multipart dependency in this backend).
    snapshot_base64: str | None = None
    source: Literal["auto", "manual"] = "auto"
    # The node could not match the read plate to a known one - a person should look.
    needs_review: bool = False

    def validate_event_type(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"Unknown event_type: {self.event_type}")


class SnapshotRequestOut(BaseModel):
    id: uuid.UUID
    bay_id: uuid.UUID
    camera_code: str | None = None  # which camera the node should grab from
    status: str
    requested_at: datetime
    completed_at: datetime | None


class PendingSnapshotRequestsResponse(BaseModel):
    requests: list[SnapshotRequestOut]


class SnapshotResult(BaseModel):
    snapshot_base64: str | None = None
    failed: bool = False


class KnownPlateOut(BaseModel):
    plate: str
    work_order_id: uuid.UUID
    work_order_number: str


class KnownPlatesResponse(BaseModel):
    plates: list[KnownPlateOut]


class HeartbeatIn(BaseModel):
    camera_code: str = Field(min_length=1, max_length=50)
    camera_ok: bool
    detail: str | None = Field(default=None, max_length=200)


class LatestFrameIn(BaseModel):
    snapshot_base64: str


class BayHistoryItem(BaseModel):
    id: uuid.UUID
    bay_id: uuid.UUID
    bay_name: str
    plate: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int
    review_status: str
    entry: BayEventOut | None
    exit: BayEventOut | None
    work_order_id: uuid.UUID | None
    work_order_number: str | None


class BayHistoryResponse(BaseModel):
    items: list[BayHistoryItem]


class BayIssueOut(BaseModel):
    id: uuid.UUID
    bay_id: uuid.UUID | None  # пусто у ошибки «нет данных из 1С»
    bay_name: str
    workshop_label: str
    kind: str
    plate: str | None
    message: str
    occurred_at: datetime
    entry_event_id: uuid.UUID | None
    resolved_at: datetime | None
    resolution: str | None
    resolved_by: str | None
    resolution_note: str | None


class BayIssuesResponse(BaseModel):
    issues: list[BayIssueOut]


class BayIssueSummary(BaseModel):
    open_count: int


class BayIssueResolveIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class GateStayOut(BaseModel):
    """Машина в кузовном цеху: заезд (въезд через ворота) и, когда выехала, выезд."""

    id: uuid.UUID
    bay_id: uuid.UUID
    bay_name: str
    plate: str | None
    label: str | None
    entered_at: datetime
    exited_at: datetime | None
    duration_seconds: int
    review_status: str
    source: str
    note: str | None
    entry: BayEventOut | None
    exit: BayEventOut | None
    # Карточка кузовного планировщика этой машины (None - в плане не нашлась).
    body_car_id: uuid.UUID | None
    car_description: str | None
    client_name: str | None
    car_status: str | None
    work_order_id: uuid.UUID | None
    work_order_number: str | None
    has_plan: bool


class GateStaysResponse(BaseModel):
    stays: list[GateStayOut]


class GateStayCreate(BaseModel):
    bay_id: uuid.UUID
    plate: str | None = Field(default=None, max_length=20)
    label: str | None = Field(default=None, max_length=200)
    entered_at: datetime | None = None


class GateStayExit(BaseModel):
    exited_at: datetime | None = None


class GateStayUpdate(BaseModel):
    plate: str | None = Field(default=None, max_length=20)
    label: str | None = Field(default=None, max_length=200)
