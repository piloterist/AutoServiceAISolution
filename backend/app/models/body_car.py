"""Кузовной цех Planner record - one car in the shop, made up of one or more
BodyCarStage rows (see body_car_stage.py) that together define its plan
timeline. `status` is the car-level state from planner_constants.CAR_STATUSES,
distinct from a stage's own name and from Слесарный SlesarkaStatus.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.planner_constants import CAR_STATUS_ACCEPT

if TYPE_CHECKING:
    from app.models.body_car_stage import BodyCarStage


class BodyCar(Base):
    __tablename__ = "body_cars"

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

    car_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    vin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    work_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    color: Mapped[str] = mapped_column(
        String(7), nullable=False
    )  # "#rrggbb", round-robin at creation
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=CAR_STATUS_ACCEPT)

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

    stages: Mapped[list["BodyCarStage"]] = relationship(
        back_populates="car", cascade="all, delete-orphan", order_by="BodyCarStage.sort_order"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<BodyCar {self.car_description!r} {self.status}>"
