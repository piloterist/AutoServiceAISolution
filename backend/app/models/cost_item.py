"""Справочник статей затрат (Настройки -> Финансы, product ask 2026-10-26):
the rows of the Финансы -> Расходы table. Only a name and an active flag -
an inactive item stays in the books (its entered amounts remain and still
count in the monthly total) but can no longer be edited."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CostItem(Base):
    __tablename__ = "cost_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Hand-set order (drag and drop in Настройки -> Финансы); the Расходы table
    # lists the items in it. New items go to the end.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CostItem {self.name!r} active={self.is_active}>"
