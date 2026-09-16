"""Request/response contracts for the 1C -> platform work order import API."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ImportLaborLineRecord(BaseModel):
    """One row of a Work Order's "Работы" (labor) tabular section."""

    operation: str | None = None
    price: Decimal | None = None
    amount: Decimal | None = None


class ImportPartLineRecord(BaseModel):
    """One row of a Work Order's "Товары" (parts) tabular section."""

    item: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None


class ImportWorkOrderRecord(BaseModel):
    """One Alpha-Auto work order as sent by the 1C export job."""

    number: str = Field(..., description="External work order number (Alpha-Auto document number)")
    date: datetime = Field(..., description="Document date")
    customer: str | None = None
    # Who actually pays - can differ from `customer` (e.g. an insurance
    # company). Optional since not every source/record will have it.
    payer: str | None = None
    car: str | None = None
    amount: Decimal
    # Plain text passthrough - no hardcoded status/department/repair-type
    # values here, whatever the client's 1C sends is stored as-is (see
    # ARCHITECTURE.md).
    status: str | None = None
    department: str | None = None
    # ЗаказНаряд.ВидРемонта - a work order attribute (accident repair,
    # scheduled maintenance, warranty, etc; exact values are per-client
    # 1C data, never hardcoded here). Captured starting now but not yet
    # wired into any read endpoint/UI - just accumulating data for when
    # that's built.
    repair_type: str | None = None
    # Four more document dates (ЗаказНаряд.ДатаСоздания/ДатаНачала/
    # ДатаОкончания/ДатаЗакрытия), distinct from `date` above. All optional -
    # 1C sends null instead of its "empty date" sentinel when a field isn't
    # filled in yet (e.g. an open order has no closed_date).
    created_date: datetime | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    closed_date: datetime | None = None
    # Not sent by 1C yet, but accepted so the API can move to a more reliable
    # external key later without a breaking contract change.
    source_key: str | None = None
    labor: list[ImportLaborLineRecord] = Field(default_factory=list)
    parts: list[ImportPartLineRecord] = Field(default_factory=list)

    # Settlement/payment state, computed by the 1C export itself by
    # reproducing 5S AUTO's own
    # пп_КлиентСервер.СписокЗаказНарядПоказатьПроцентОплаты() logic
    # (РегистрНакопления.ВзаиморасчетыКомпании.Остатки()) - never
    # recomputed on this side from raw payment documents, see
    # 1c/TestExportOrders.bsl. All optional so older export files (and any
    # work order 1C hasn't priced) keep importing unchanged.
    deal_amount: Decimal | None = None
    debt_amount: Decimal | None = None
    paid_amount: Decimal | None = None
    # Deliberately unbounded (not clamped to 0..100) - 5S AUTO itself
    # allows a negative percent or one past 100% (overpayment), and that's
    # real data worth keeping for analytics, not an error to normalize away.
    payment_percent: Decimal | None = None


class ImportWorkOrdersRequest(BaseModel):
    source: str = Field(..., description='e.g. "alpha-auto"')
    branch: str | None = None
    entity: str = Field(..., description='e.g. "work_orders"')
    exported_at: datetime
    batch_id: str
    records: list[ImportWorkOrderRecord] = Field(default_factory=list)


class ImportWorkOrdersResponse(BaseModel):
    status: str
    received: int
    inserted: int
    updated: int
    batch_id: str
