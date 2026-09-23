"""Слесарный цех Planner record - one car booked into one post for a time
slot on a given day (product brief part 4). `work_order_id` links it to the
real ЗН when one was picked in the dialog; the car/VIN/plate/client fields
are still stored on the row itself (not always looked up live) since they
can also be typed by hand when no ЗН is linked yet. `amount` is
deliberately NOT a column here - the brief says "Сумма - тянем из
заказ-наряда", i.e. always a live read of work_order.amount through the FK,
never a snapshot that could go stale.
"""

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Time, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkshopJob(Base):
    __tablename__ = "workshop_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workshop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workshops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    car_description: Mapped[str | None] = mapped_column(String(500), nullable=True)  # Автомобиль
    vin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    plate: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # Гос.номер - manual only, see module docstring
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Клиент
    # Filled from the linked ЗН when picked, or typed by hand - same pattern
    # as car_description/plate/client_name above, not a live FK read.
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Who's assigned to this record - picked from the employees directory,
    # shown last on the job card (see MechanicalView.tsx).
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    work_description: Mapped[str | None] = mapped_column(Text, nullable=True)  # Работы

    job_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    post_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    norm_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 1), nullable=True
    )  # пусто пока, см. бриф

    status_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("slesarka_statuses.id", ondelete="SET NULL"), nullable=True
    )

    # SET NULL, not CASCADE/RESTRICT: deleting a user must not delete or
    # block deleting their past schedule entries - see
    # models/schedule_audit_log.py for the same reasoning.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WorkshopJob {self.job_date} post={self.post_number} {self.start_time}>"
