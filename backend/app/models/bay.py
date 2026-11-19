"""Бокс цеха и события видеоконтроля (въезд/выезд автомобиля).

Бокс (Bay) принадлежит цеху (Workshop). События (BayEvent) - неизменяемый журнал
того, что увидел узел видеоконтроля на площадке (или поправил человек); интервалы
занятости (BayOccupancy) выводятся из подтверждённых событий. Заказ-наряд по одному
выезду НЕ закрывается: у одного номера бывает несколько интервалов за день
(тест-драйв, возврат, смена бокса), поэтому интервал - отдельная сущность.

Снимки хранятся на Яндекс.Диске (см. services/bay_service.py), здесь только путь.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

EVENT_PLATE_OBSERVED = "plate_observed"
EVENT_ENTRY_CANDIDATE = "entry_candidate"
EVENT_ENTRY_CONFIRMED = "entry_confirmed"
EVENT_EXIT_CANDIDATE = "exit_candidate"
EVENT_EXIT_CONFIRMED = "exit_confirmed"
EVENT_MANUAL_CORRECTION = "manual_correction"
EVENT_TYPES = (
    EVENT_PLATE_OBSERVED,
    EVENT_ENTRY_CANDIDATE,
    EVENT_ENTRY_CONFIRMED,
    EVENT_EXIT_CANDIDATE,
    EVENT_EXIT_CONFIRMED,
    EVENT_MANUAL_CORRECTION,
)

SOURCE_AUTO = "auto"
SOURCE_MANUAL = "manual"
REVIEW_AUTO = "auto"
REVIEW_NEEDS = "needs_review"
REVIEW_CONFIRMED = "confirmed"

BAY_KIND_BAY = "bay"
BAY_KIND_GATE = "gate"

SNAPSHOT_PENDING = "pending"
SNAPSHOT_DONE = "done"
SNAPSHOT_FAILED = "failed"


class Bay(Base):
    __tablename__ = "bays"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workshop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workshops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Код камеры на площадке (узел видеоконтроля сопоставляет бокс с камерой по нему).
    camera_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # "bay" - бокс (одна машина, слесарный); "gate" - ворота кузовного цеха: машина проезжает под
    # камерой, не останавливаясь, а внутри их может быть много (GateStay, services/gate_service.py).
    kind: Mapped[str] = mapped_column(
        String(10), nullable=False, default=BAY_KIND_BAY, server_default=BAY_KIND_BAY
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BayEvent(Base):
    __tablename__ = "bay_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bays.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    # Путь снимка на Яндекс.Диске, например "disk:/Bays/<bay>/<event>.jpg".
    snapshot_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True
    )
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=REVIEW_AUTO, server_default=REVIEW_AUTO
    )
    source: Mapped[str] = mapped_column(
        String(10), nullable=False, default=SOURCE_AUTO, server_default=SOURCE_AUTO
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BayOccupancy(Base):
    __tablename__ = "bay_occupancy"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bays.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bay_events.id", ondelete="CASCADE"), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bay_events.id", ondelete="SET NULL"), nullable=True
    )
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=REVIEW_AUTO, server_default=REVIEW_AUTO
    )
    # Запись планировщика (слесарный цех), которую этот заезд перевёл в работу или создал.
    # По ней запись продлевается, пока машина в боксе, и становится «Готова» после выезда.
    workshop_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workshop_jobs.id", ondelete="SET NULL"), nullable=True
    )


class BaySnapshotRequest(Base):
    """Запрос «получить текущий кадр из бокса». Облако не может подключиться к камере
    в локальной сети, поэтому кнопка на странице создаёт запрос, а узел на площадке
    (раз в несколько секунд опрашивает облако по исходящему HTTPS) снимает кадр и
    загружает его."""

    __tablename__ = "bay_snapshot_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bays.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=SNAPSHOT_PENDING, server_default=SNAPSHOT_PENDING
    )
    # Живой кадр - временный (десятки секунд жизни), поэтому хранится прямо в базе, а не
    # на Яндекс.Диске: быстрее и не зависит от сети до Диска. Старые кадры бокса стираются.
    image: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


ISSUE_NO_WORK_ORDER = "no_work_order"
ISSUE_NO_BODY_PLAN = "no_body_plan"  # въехала машина, а в плане кузовного её нет
ISSUE_EXIT_WITHOUT_ENTRY = "exit_without_entry"  # выезд машины, которой нет в цехе
ISSUE_RESOLVED_AUTO = "auto"
ISSUE_RESOLVED_MANUAL = "manual"


class BayIssue(Base):
    """Ошибка видеоконтроля, которую должен разобрать управляющий (лист «Ошибки»).
    Сейчас одна причина: машина стоит в боксе, а заказ-наряда по её номеру нет."""

    __tablename__ = "bay_issues"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bays.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occupancy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bay_occupancy.id", ondelete="SET NULL"), nullable=True
    )
    entry_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bay_events.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(10), nullable=True)  # auto / manual
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class GateStay(Base):
    """Машина в кузовном цеху: от проезда ворот на въезд до проезда на выезд. Таких одновременно
    открыто сколько угодно (5, 10 и больше), между въездом и выездом проезжают другие. Один номер
    за период может иметь несколько заездов (выехала на покраску и вернулась) - все они привязаны
    к одной карточке кузовного планировщика (body_car_id)."""

    __tablename__ = "gate_stays"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bays.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Описание машины без номера (вводится руками): «Белый Рио, без номеров».
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bay_events.id", ondelete="SET NULL"), nullable=True
    )
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bay_events.id", ondelete="SET NULL"), nullable=True
    )
    body_car_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("body_cars.id", ondelete="SET NULL"), nullable=True
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True
    )
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=REVIEW_AUTO, server_default=REVIEW_AUTO
    )
    source: Mapped[str] = mapped_column(
        String(10), nullable=False, default=SOURCE_AUTO, server_default=SOURCE_AUTO
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CameraStatus(Base):
    """Сердцебиение узла на площадке по камере: когда видели в последний раз и отдаёт ли
    камера видео (и с какого момента - для «камера недоступна уже N минут»)."""

    __tablename__ = "camera_status"

    camera_code: Mapped[str] = mapped_column(String(50), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    camera_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    camera_ok_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)


class BayLatestFrame(Base):
    """Последний кадр бокса: узел присылает его раз в минуту, всегда. Одна строка на бокс,
    новый кадр заменяет предыдущий (старые не копим). Страница показывает его в окне «Сейчас»,
    а в пустом боксе - во всех трёх окнах."""

    __tablename__ = "bay_latest_frames"

    bay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bays.id", ondelete="CASCADE"), primary_key=True
    )
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
