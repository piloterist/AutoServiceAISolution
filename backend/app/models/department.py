"""Подразделение (department) - e.g. "Каховка", "Солнцево".

Plain client data, edited from Settings by an Admin - not hardcoded, same
reasoning as WorkOrder.department (see ARCHITECTURE.md). Distinct from that
free-text field on WorkOrder (which comes from 1C, not from here) - this
table is the product's own structural list a Workshop/User belongs to for
the Planner (see models/workshop.py, models/user.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Department {self.name!r}>"
