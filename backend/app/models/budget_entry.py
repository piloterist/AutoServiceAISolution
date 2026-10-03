"""Бюджет page's own manually-entered numbers - "Выручка план" and
"Расходы" per workshop/year/month (everything else on that page - факт
revenue, payments, profit, money - is computed on the fly from WorkOrder/
WorkOrderPaymentEvent, same as Cockpit, see services/budget_service.py).

One row per (workshop, year, month) that actually has a manually-entered
value - a cell nobody has touched yet simply has no row at all, read back
as None/0 rather than a stored zero.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BudgetEntry(Base):
    __tablename__ = "budget_entries"
    __table_args__ = (
        UniqueConstraint("workshop_id", "year", "month", name="uq_budget_entry_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workshop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workshops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-12

    plan_revenue: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    expenses: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<BudgetEntry {self.workshop_id} {self.year}-{self.month:02d}>"
