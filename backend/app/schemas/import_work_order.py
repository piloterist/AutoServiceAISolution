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


class ImportPaymentEventRecord(BaseModel):
    """One real, dated payment movement toward this work order's settlement -
    a raw РегистрНакопления.ВзаиморасчетыКомпании row (ВидДвижения=Расход,
    an actual money-in event), not the Остатки() running-balance snapshot
    above. See 1c/TestExportOrders.bsl's payments batch query and
    models/work_order_payment_event.py for how "this row means a real
    payment" was derived from the register's own structure."""

    paid_at: datetime
    amount: Decimal
    source_document_id: str
    source_document_type: str | None = None
    source_document_number: str | None = None
    line_number: int = 1


class ImportStatusHistoryRecord(BaseModel):
    """One РегистрСведений.пп_ВерсииОбъектов version of this work order,
    with its resolved Справочник.ВидыСостоянийЗаказНарядов status - see
    1c/TestExportOrders.bsl for how this is read (strictly read-only
    against 1C: Запрос.Выполнить() + ХранилищеЗначения.Получить(), never
    Объект.Записать()).

    Not every version is a real status change - a version can exist
    because ANY requisite changed (amount, labor lines, comment, ...), not
    just Состояние. `status` is None when this specific version's snapshot
    didn't resolve to a status (missing/unreadable/corrupt - see
    services/import_service.py for how those are skipped, not treated as
    "no status"). Send every available version unfiltered - the backend
    collapses consecutive versions with the same status into a single
    status_history row."""

    version_number: int
    changed_at: datetime
    author: str | None = None
    status: str | None = None
    status_uuid: str | None = None


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
    # 1C data, never hardcoded here). Shown on the work order detail page.
    repair_type: str | None = None
    # ЗаказНаряд.Организация - which of the client's own legal entities the
    # work order was raised under.
    organization: str | None = None
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
    # Real dated payment ledger for this work order - empty when the export
    # doesn't send it (older BSL versions, or a work order with no payments
    # yet). See ImportPaymentEventRecord above.
    payment_events: list[ImportPaymentEventRecord] = Field(default_factory=list)
    # Real status change history from 1C's own version log - replaces the
    # old import-diff-based mechanism entirely. Empty when the export
    # doesn't send it (older BSL versions, or a work order with no
    # available version history in 1C). See ImportStatusHistoryRecord above.
    status_history: list[ImportStatusHistoryRecord] = Field(default_factory=list)


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
