"""Счёт на оплату (Документ.СчетНаОплату) linked to a Work Order.

Distinct from work_order_payment_events (real, dated money-in movements):
this is the invoice itself - what was billed, when, and how much of it has
been paid so far - not a payment transaction. One invoice always belongs to
exactly one Work Order (`Счет.ДокументОснование = ЗН.Ссылка`, a direct
reference-equality link, not a chain through ДокументОснование/
ОснованиеОснования - see 1c/TestExportOrders.bsl's step 2b), so
`work_order_id` is required, never nullable.

`paid_amount`/`debt_amount` are computed by the 1C export itself, scoped to
payments found against this specific invoice (the same
`СуммаПлатежейПоСчету`/`МАКС(0, ...)` logic already used for the Work
Order's own debt/paid credit from linked invoices) - never recomputed here,
same convention as WorkOrder.deal_amount/debt_amount/paid_amount. There is
no `status` enum column: Alpha-Auto's own status field(s) for this document
type haven't been confirmed yet (see CLAUDE.md part 40 - model from actual
facts, not assumptions), so "paid / partially paid / unpaid" is derived
from amount vs paid_amount at read time instead of guessed and stored.

`source_document_id` is the invoice's own 1C GUID
(Счет.Ссылка.УникальныйИдентификатор()) - the natural idempotency key for
upsert, mirroring WorkOrder.source_key and
WorkOrderPaymentEvent.source_document_id.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkOrderInvoice(Base):
    __tablename__ = "work_order_invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    source_document_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    external_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    debt_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    posted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WorkOrderInvoice {self.external_number!r} {self.work_order_id}>"
