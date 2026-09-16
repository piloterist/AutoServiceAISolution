"""Append-only snapshots of a Work Order's payment/settlement state.

Unlike work_order_status_history (a segmented timeline - a work order is
*in* exactly one status at a time, with an explicit open/close per segment),
payment state is a single current value (deal_amount, debt_amount,
paid_amount, payment_percent) that just drifts over time as payments post
in 1C - there's no "segment" to open or close, only "what did it look like
at each observed moment". A new row is only appended when at least one of
those values actually changed since the last snapshot (see
services/import_service.py::_record_payment_history) - an unchanged
payment state on a later import doesn't add a row.

This is deliberately the minimal shape that lets the product eventually
answer "when was this work order first paid", "how did the debt change
over time", "when did it reach 100%" - not a general event-sourcing
mechanism for the whole product.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkOrderPaymentHistory(Base):
    __tablename__ = "work_order_payment_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    deal_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    debt_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    payment_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WorkOrderPaymentHistory {self.work_order_id} {self.observed_at}>"
