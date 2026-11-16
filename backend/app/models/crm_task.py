"""Задача на «Доске задач» CRM (product ask, 2026-11-15) - один телефон клиента, взятый на контроль
со звонка. Столбец доски - это `status`; как карточка двигается между столбцами - см.
services/crm_task_service.py.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Столбцы доски, в порядке слева направо.
TASK_STATUS_CONTROL = "control"  # На контроле
TASK_STATUS_INSPECTION = "inspection"  # Записан на осмотр
TASK_STATUS_THINKING = "thinking"  # Думает
TASK_STATUS_REFUSED = "refused"  # Отказ
TASK_STATUS_WORK_ORDER = "work_order"  # Заказ-наряд
TASK_STATUSES = (
    TASK_STATUS_CONTROL,
    TASK_STATUS_INSPECTION,
    TASK_STATUS_THINKING,
    TASK_STATUS_REFUSED,
    TASK_STATUS_WORK_ORDER,
)


class CrmTask(Base):
    __tablename__ = "crm_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Номер клиента - последние 10 цифр, как в telephony_calls.client.
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # Звонок, с которого задачу взяли на контроль. Всё, что "появляется" по этому телефону
    # (запись в планировщике, заявка, заказ-наряд), должно быть позже него (или позже
    # последнего ручного перемещения) - иначе зацепится прошлое клиента.
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telephony_calls.id", ondelete="SET NULL"), nullable=True
    )
    call_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Цех звонка (telephony_calls.workshop_id) - по нему фильтруется доска и счётчик планировщика.
    workshop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workshops.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Сотрудник цеха, который ведёт этот телефон (необязателен; фильтр доски по сотруднику).
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TASK_STATUS_CONTROL, index=True
    )
    # Когда карточка попала в текущий столбец - от этого момента идут розовый/красный сроки
    # столбца «На контроле».
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Когда карточку в последний раз переносили руками: автоматика ищет события позже него.
    manual_moved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Когда клиент записан на осмотр (создание записи в планировщике кузовного цеха): заявка
    # на ремонт должна быть позже этого момента.
    inspection_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Дата осмотра по этапу «Осмотр» записи в планировщике (у этапа только даты, без времени):
    # с - по (одинаковые, если осмотр в один день). Для показа на карточке.
    inspection_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    inspection_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Запись планировщика, с которой связана карточка в «Записан на осмотр»: кузовной (BodyCar) или
    # слесарный (WorkshopJob). Возврат из «Записан на осмотр» в «На контроле» удаляет её.
    body_car_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("body_cars.id", ondelete="SET NULL"), nullable=True
    )
    workshop_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workshop_jobs.id", ondelete="SET NULL"), nullable=True
    )

    # Последняя запланированная дата следующего действия (контакта) - от неё, а не от
    # status_changed_at, считаются розовый и красный сроки в «На контроле». История - в
    # CrmTaskAction.
    next_action_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Что нашла автоматика (для показа на карточке).
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    car_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    work_order_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    refuse_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(255), nullable=False)
    moved_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CrmTask {self.phone} {self.status}>"


class CrmTaskComment(Base):
    """Комментарий к карточке доски (product ask, 2026-11-15): можно оставить на любом этапе;
    `status` - в каком столбце была карточка в этот момент. Причина отказа тоже попадает сюда."""

    __tablename__ = "crm_task_comments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CrmTaskAction(Base):
    """Запланированное действие по карточке: дата контакта + обязательный комментарий. Планировать
    можно сколько угодно раз; действует последняя дата (CrmTask.next_action_date)."""

    __tablename__ = "crm_task_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    planned_date: Mapped[date] = mapped_column(Date, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
