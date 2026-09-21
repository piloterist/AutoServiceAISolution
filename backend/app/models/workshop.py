"""Цех (workshop) - a physical shop floor within a Department, e.g. "Каховка
/ Кузовной". Drives the Planner (see PLAN.md-style spec in the product
brief): which shops exist per department, how many posts each has, its
working hours/days, and which one opens by default.

`workshop_type` is one of WORKSHOP_TYPES below - unlike Department (pure
client data), the Planner branches its entire UI/scheduling model on this
value (Кузовной = multi-day stage timeline, Слесарный = per-post/per-30-min
grid), so it is a closed set validated at the schema layer
(schemas/workshop.py), not free text - same reasoning as User.role.
"""

import uuid
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Time, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

WORKSHOP_TYPE_BODY = "Кузовной"
WORKSHOP_TYPE_MECHANICAL = "Слесарный"
WORKSHOP_TYPES = (WORKSHOP_TYPE_BODY, WORKSHOP_TYPE_MECHANICAL)

# Python's date.weekday(): 0=Monday .. 6=Sunday - `working_days` stores a
# subset of these, chosen from Settings ("любое количество дней от
# понедельника до воскресенья").
WEEKDAY_CHOICES = (0, 1, 2, 3, 4, 5, 6)


class Workshop(Base):
    __tablename__ = "workshops"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workshop_type: Mapped[str] = mapped_column(String(20), nullable=False)

    area: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)  # площадь
    posts_count: Mapped[int] = mapped_column(Integer, nullable=False)  # посты

    # Default workshop to open for a user who has no personal department/
    # workshop preference set (see User.department_id/workshop_id) - at most
    # one is meaningfully "the" default per department, but that's a
    # service-layer concern (services/workshop_service.py), not a DB
    # constraint, since having none set is a valid transient state.
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    start_time: Mapped[time] = mapped_column(Time, nullable=False)  # Начало, напр. 07:00
    end_time: Mapped[time] = mapped_column(Time, nullable=False)  # Конец, напр. 22:00
    # Subset of WEEKDAY_CHOICES.
    working_days: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Workshop {self.department_id}/{self.workshop_type}>"
