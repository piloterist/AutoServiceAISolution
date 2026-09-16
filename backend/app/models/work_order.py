"""WorkOrder - the central business entity of the product.

Everything else in the product (revenue, cost, parts, labor, staff load,
margin, statuses, deadlines, reporting) is built around the Work Order, not
around the Vehicle. This model intentionally stays minimal: it only encodes
fields confirmed from the Alpha-Auto source so far. Do not model the full
Alpha-Auto schema here yet - it is still being explored.

Identity note: `source_key` exists so the architecture can move to a more
reliable external key later without a breaking migration; today the natural
key used for de-duplication is (source_system, external_number).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "external_number",
            name="uq_work_orders_source_system_external_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    external_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(
        String(50), nullable=False, default="alpha-auto", server_default="alpha-auto"
    )
    source_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    document_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Four more dates from Alpha-Auto's own document requisites, distinct
    # from `document_date` (ЗаказНаряд.Дата, the plain document date/number
    # sequencing field). All nullable - an open work order won't have a
    # closed_date yet, and the source only sends a value when the 1C field
    # is actually filled in (its "empty date" sentinel is translated to
    # null on export, not sent as a fake date - see 1c/TestExportOrders.bsl).
    created_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # ДатаСоздания
    start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # ДатаНачала
    end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # ДатаОкончания
    # Indexed: this is the date revenue reporting groups/filters by (see
    # services/work_order_query_service.py) - a work order's revenue is
    # attributed to the month it was actually closed in, not created in.
    closed_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )  # ДатаЗакрытия

    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Payer can differ from the customer (e.g. an insurance company paying
    # for a customer's repair) - a distinct field, not derived from customer.
    payer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vehicle_description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Plain text, whatever the source sends - no hardcoded status/department/
    # repair-type values or enums here (client-specific, must stay
    # configuration/data, never baked into the core - see ARCHITECTURE.md).
    status: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    # ЗаказНаряд.ВидРемонта - captured starting now (see
    # schemas/import_work_order.py) but not yet read/displayed anywhere.
    repair_type: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)

    # Money is never stored as float - fixed-precision NUMERIC only.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    # Settlement/payment state as of the last import - 5S AUTO's own
    # РегистрНакопления.ВзаиморасчетыКомпании.Остатки() calculation,
    # reproduced batched in the 1C export itself (see
    # 1c/TestExportOrders.bsl) and sent as-is; never recomputed here from
    # raw payment documents. All nullable - older exports (and any work
    # order 1C hasn't priced yet) simply don't send these.
    deal_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    debt_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Deliberately not bounded to 0..100 - 5S AUTO's own figure can go
    # negative or past 100% (overpayment produces debt_amount < 0), and
    # that's real data worth keeping, not an error to clamp away.
    payment_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WorkOrder {self.source_system}:{self.external_number}>"
