"""Maps a raw `WorkOrder.department` string (as sent by 1C - messy,
workshop-type-embedded, e.g. "Кузовной цех (Каховка)", "Слесарный
цех_(ИП Пан)") to a real Workshop.

WorkOrder has no real `workshop_id`/`department_id` FK, only that free-text
`department` column (see models/work_order.py) - and on real client data
those strings don't match Department.name at all, so services/
cockpit_service.py (revenue/payments/НЗП scoped "по цеху") needs an
explicit, operator-maintained mapping rather than guessing via name/
substring matching, which would silently misattribute revenue whenever a
client's 1C department strings don't follow a predictable pattern.

Many-to-one: a single Workshop commonly absorbs several raw strings (e.g.
a client renamed a department in 1C over time, or uses a sub-label like
"(Ингос)" for an insurance case) - the unique constraint on
`source_department` below is what keeps this one-directional: one raw
string can only ever mean one Workshop, never split across two.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkshopSourceDepartment(Base):
    __tablename__ = "workshop_source_departments"
    __table_args__ = (
        UniqueConstraint(
            "source_department", name="uq_workshop_source_departments_source_department"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workshop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workshops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Exact WorkOrder.department value, as 1C sends it.
    source_department: Mapped[str] = mapped_column(String(150), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WorkshopSourceDepartment {self.source_department!r} -> {self.workshop_id}>"
