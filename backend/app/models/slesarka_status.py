"""Статусы слесарки - the configurable status list + color for records on
the Слесарный workshop Planner grid (see models for the Planner's own
schedule entries, added alongside the Planner feature itself). Seeded with
the four statuses the product brief names (Запись/В работе/Готова/Отмена);
editable/extendable from Settings, so a status's own display name is data,
not a hardcoded enum, like WorkOrder.status.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SlesarkaStatus(Base):
    __tablename__ = "slesarka_statuses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    # "#rrggbb" - picked from a color palette in Settings.
    color: Mapped[str] = mapped_column(String(7), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SlesarkaStatus {self.name!r} {self.color}>"
