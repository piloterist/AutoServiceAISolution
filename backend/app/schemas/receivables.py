"""Contract for the Финансы -> Дебитор­ская задолженность tab - see
services/receivables_service.py."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

# Keep in sync with receivables_service.AGING_BUCKET_KEYS.
AGING_BUCKET_KEYS = ["lt_10", "d10_30", "d30_60", "d60_90", "gte_90"]


class ReceivablesAgingRow(BaseModel):
    work_order_id: UUID
    work_order_number: str
    status: str | None
    customer_name: str | None
    is_individual_customer: bool
    closed_date: datetime | None
    # The work order's own Счет на оплату date, if it has one - None when it
    # doesn't (displayed as its own "Дата счета" column, distinct from
    # reference_date below, which silently falls back to closed_date).
    invoice_date: datetime | None
    # The date aging is measured from - invoice_date if present, else
    # closed_date. See receivables_service.get_aging_report.
    reference_date: datetime | None
    days_overdue: int
    debt_amount: Decimal
    bucket: str  # one of AGING_BUCKET_KEYS
    # ЗаказНаряд.ВидРемонта - drives the Все/Страховые/Текущие filter on the
    # frontend (see AppSettings.insurance_repair_type/warranty_repair_types
    # below and ReceivablesAgingView.tsx), applied client-side same as the
    # existing date-range/Физ.лицо filters on this same table.
    repair_type: str | None


class ReceivablesAgingTotals(BaseModel):
    lt_10: Decimal
    d10_30: Decimal
    d30_60: Decimal
    d60_90: Decimal
    gte_90: Decimal
    total: Decimal


class ReceivablesAgingResponse(BaseModel):
    as_of: datetime
    rows: list[ReceivablesAgingRow]
    totals: ReceivablesAgingTotals
    # Mirrors AppSettings - product ask, 2026-10-23: the Все/Страховые/
    # Текущие filter needs to know which ВидРемонта value means "страховой"
    # and which ones mean "гарантийный" to classify each row client-side.
    insurance_repair_type: str | None
    warranty_repair_types: list[str]
