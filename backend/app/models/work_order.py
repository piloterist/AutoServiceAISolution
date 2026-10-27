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

from sqlalchemy import (
    Boolean,
    DateTime,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column, with_loader_criteria

from app.db.base import Base

# Document kinds stored in this table. A "repair request" (1C: Заявка на ремонт)
# is a free visit for a defect check and an estimate - it looks like a work order
# (header, labor and part lines) but is NOT one: it has no revenue, payments or
# debt, and must stay out of every work-order figure (revenue, receivables,
# conversion, kanban...) - see the do_orm_execute filter at the end of this file.
# Its source_system is "<source>-repair_request", not the work orders' "alpha-auto":
# 1C numbers the two kinds with the same prefixes and sequences, so they cannot
# share the (source_system, external_number) key.
DOC_TYPE_WORK_ORDER = "work_order"
DOC_TYPE_REPAIR_REQUEST = "repair_request"


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
    # ЗаказНаряд.НомерТелефона - shown on the work order card and used to
    # pre-fill the Planner record's own phone field when a ЗН is picked.
    phone: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Payer can differ from the customer (e.g. an insurance company paying
    # for a customer's repair) - a distinct field, not derived from customer.
    payer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vehicle_description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Plain text, whatever the source sends - no hardcoded status/department/
    # repair-type values or enums here (client-specific, must stay
    # configuration/data, never baked into the core - see ARCHITECTURE.md).
    status: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    # ЗаказНаряд.ВидРемонта - shown on the work order detail page.
    repair_type: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    # ЗаказНаряд.Организация - which of the client's own legal entities the
    # work order was raised under (relevant for multi-entity operations).
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # "work_order" (Заказ-наряд) or "repair_request" (Заявка на ремонт) - see
    # DOC_TYPE_* above. Every ORM SELECT of WorkOrder hides the requests unless it
    # sets the execution option include_repair_requests (the work order list and card).
    doc_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DOC_TYPE_WORK_ORDER,
        server_default=DOC_TYPE_WORK_ORDER,
        index=True,
    )
    # Repair requests only: numbers of the work orders created from this request
    # (1C: ЗаказНаряд.ДокументОснование = the request), comma-separated; NULL while none.
    linked_work_orders: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ЗаказНаряд.Автомобиль.VIN - raw passthrough from 1C's vehicle catalog,
    # shown on the work order detail card only (never on the list/dashboard -
    # see ARCHITECTURE.md-style scoping notes in services/internal_order_rules.py).
    # Distinct from `car_key` below, which is this value validated/normalized
    # for matching, not for display.
    vin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Validated/normalized VIN (see internal_order_rules.normalize_vin), or
    # NULL when `vin` isn't a real 17-character VIN - the key
    # recompute_internal_flags groups work orders by to detect "внутренний"
    # ones (same car, an external/страховой sibling). Indexed since every
    # import looks this up by a set of car_keys.
    car_key: Mapped[str | None] = mapped_column(String(17), nullable=True, index=True)
    # Computed by recompute_internal_flags (see services/import_service.py
    # and services/internal_order_rules.py) after every import - never set
    # directly from the 1C export. Indexed: dashboard queries filter on it
    # when AppSettings.exclude_internal_orders is on.
    is_internal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )

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

    # Free-text staff note (product ask, 2026-10-06) - purely internal,
    # never sent by or to 1C. Deliberately absent from `_upsert_work_order`'s
    # own `values`/`update_columns` (see services/import_service.py), so a
    # re-import can never touch/reset it.
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Staff-set "Закрыть без оплат" flag (product ask, 2026-10-07): some
    # work orders are closed by an off-system arrangement and will never
    # actually get paid, which was inflating the ДЗ (receivables) figure
    # and list with debt that's never coming. Settable only by the Админ
    # role (enforced in the frontend's own API route/middleware - there is
    # no per-request backend auth yet, see endpoints/work_orders.py). Same
    # pattern as `comment` above: purely internal, never sent by/to 1C, and
    # deliberately absent from `_upsert_work_order`'s values/update_columns
    # so a re-import can never reset it. See work_order_query_service.
    # list_work_orders's only_receivables filter and cockpit_service.
    # _receivables for where this actually excludes a work order from ДЗ.
    closed_without_payment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

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


@event.listens_for(Session, "do_orm_execute")
def _hide_repair_requests(state) -> None:
    """Keeps repair requests out of every ORM SELECT of work orders (also in
    joins, subqueries and aliases), so no revenue/receivables/conversion/kanban
    query has to remember to filter them. A query that does want them passes
    execution_options={"include_repair_requests": True}."""
    if (
        state.is_select
        and not state.is_column_load
        and not state.is_relationship_load
        and not state.execution_options.get("include_repair_requests", False)
    ):
        state.statement = state.statement.options(
            with_loader_criteria(
                WorkOrder,
                lambda cls: cls.doc_type == DOC_TYPE_WORK_ORDER,
                include_aliases=True,
            )
        )
