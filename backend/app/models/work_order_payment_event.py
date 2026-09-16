"""Real, dated payment movements toward a Work Order's settlement.

Unlike work_order_payment_history (a periodic snapshot of the *running
balance* - deal/debt/paid/percent as of each import), this is a ledger of
individual payment transactions, one row per raw
РегистрНакопления.ВзаиморасчетыКомпании movement that actually represents
money received (ВидДвижения=Расход, ВидОперации one of "Погашение
дебиторской задолженности" / "Начисление кредиторской задолженности" - see
1c/TestExportOrders.bsl for how this was derived from the register's real
structure, not guessed). `paid_at` is 1C's own movement date (Период), the
real moment the payment posted - not an import/observation timestamp.

`source_document_id` is the 1C payment document's own UUID
(Регистратор.УникальныйИдентификатор()) - the natural idempotency key, since
the same historical payment gets re-sent on every full re-export.
`line_number` disambiguates multiple register rows from the same document
(rare, but possible).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkOrderPaymentEvent(Base):
    __tablename__ = "work_order_payment_events"
    __table_args__ = (
        UniqueConstraint(
            "work_order_id",
            "source_document_id",
            "line_number",
            name="uq_work_order_payment_events_document_line",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    source_document_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_document_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    source_document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<WorkOrderPaymentEvent {self.work_order_id} "
            f"{self.source_document_id}#{self.line_number}>"
        )
