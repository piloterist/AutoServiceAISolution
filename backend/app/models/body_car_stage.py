"""One этап (stage) of a Кузовной BodyCar's plan timeline - see body_car.py.

`sort_order` is the authoritative row order (not `start_date`, which
several stages can share) - it's what the recalculate-later-stages-on-
delete logic in services/planner_service.py walks in order.
"""

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BodyCarStage(Base):
    __tablename__ = "body_car_stages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    body_car_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("body_cars.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    stage_name: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # one of planner_constants.BODY_STAGE_TYPES
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    car = relationship("BodyCar", back_populates="stages")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<BodyCarStage {self.stage_name} {self.start_date}-{self.end_date}>"
