"""One entered amount of Финансы -> Расходы: a cost item, in a workshop, for
a month. The month's total per workshop feeds the Бюджет "Расходы" row (see
services/budget_service.py). A cell nobody filled simply has no row."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CostExpense(Base):
    __tablename__ = "cost_expenses"
    __table_args__ = (
        UniqueConstraint(
            "cost_item_id", "workshop_id", "year", "month", name="uq_cost_expense_cell"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cost_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cost_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    workshop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workshops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-12
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CostExpense {self.cost_item_id} {self.workshop_id} {self.year}-{self.month:02d}>"
