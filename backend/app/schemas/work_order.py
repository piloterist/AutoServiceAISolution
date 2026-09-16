"""Read-side contracts for browsing/reporting on Work Orders.

Separate from schemas/import_work_order.py (the write-side 1C contract) on
purpose - the two evolve independently.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class WorkOrderListItem(BaseModel):
    id: UUID
    external_number: str
    document_date: datetime
    # Alpha-Auto's own document requisites (ДатаСоздания/ДатаНачала/
    # ДатаОкончания/ДатаЗакрытия) - distinct from document_date above.
    created_date: datetime | None
    start_date: datetime | None
    end_date: datetime | None
    closed_date: datetime | None
    customer_name: str | None
    payer_name: str | None
    vehicle_description: str | None
    status: str | None
    department: str | None
    amount: Decimal
    # Settlement state as of the last import - 5S AUTO's own
    # ВзаиморасчетыКомпании calculation (see
    # schemas/import_work_order.py), not recomputed here. None on either
    # field just means the source export didn't send payment data for this
    # work order yet (older export, or before 1C priced it).
    deal_amount: Decimal | None
    debt_amount: Decimal | None
    paid_amount: Decimal | None
    payment_percent: Decimal | None

    model_config = {"from_attributes": True}


class WorkOrderListResponse(BaseModel):
    items: list[WorkOrderListItem]
    total: int
    limit: int
    offset: int


class MonthlySummaryItem(BaseModel):
    month: str  # "YYYY-MM"
    work_order_count: int
    total_amount: Decimal


class MonthlySummaryResponse(BaseModel):
    items: list[MonthlySummaryItem]


class TrendSummaryItem(BaseModel):
    period: str  # "YYYY-MM-DD" - start of the bucket (day/week/month)
    work_order_count: int
    total_amount: Decimal


class TrendSummaryResponse(BaseModel):
    items: list[TrendSummaryItem]
    granularity: str  # "day" | "week" | "month"


class PaymentTrendItem(BaseModel):
    period: str  # "YYYY-MM-DD" - start of the bucket (day/week/month)
    # Net change in paid_amount observed in this bucket - see
    # work_order_query_service.payment_trend_summary for exactly what this
    # does and doesn't mean (there is no real payment date available).
    total_amount: Decimal


class PaymentTrendResponse(BaseModel):
    items: list[PaymentTrendItem]
    granularity: str  # "day" | "week" | "month"


class DepartmentSummaryItem(BaseModel):
    department: str
    work_order_count: int
    total_amount: Decimal


class DepartmentSummaryResponse(BaseModel):
    items: list[DepartmentSummaryItem]


class DepartmentListResponse(BaseModel):
    departments: list[str]


class StatusSummaryItem(BaseModel):
    status: str
    work_order_count: int
    total_amount: Decimal


class StatusSummaryResponse(BaseModel):
    items: list[StatusSummaryItem]


class WorkOrderLaborLineItem(BaseModel):
    operation_name: str | None
    price: Decimal | None
    amount: Decimal | None

    model_config = {"from_attributes": True}


class WorkOrderPartLineItem(BaseModel):
    item_name: str | None
    quantity: Decimal | None
    price: Decimal | None
    amount: Decimal | None

    model_config = {"from_attributes": True}


class StatusHistoryItem(BaseModel):
    status: str
    first_seen_at: datetime
    # None = this is the currently-open segment (still the work order's
    # status as of the most recent import) - the frontend computes its
    # duration against "now", not a value from here.
    last_seen_at: datetime | None

    model_config = {"from_attributes": True}


class PaymentHistoryItem(BaseModel):
    observed_at: datetime
    deal_amount: Decimal | None
    debt_amount: Decimal | None
    paid_amount: Decimal | None
    payment_percent: Decimal | None

    model_config = {"from_attributes": True}


class WorkOrderDetail(WorkOrderListItem):
    """Single work order's header (same fields as the list) plus its labor
    (Работы) and parts (Товары) tabular-section lines, its status timeline
    (oldest first - see models/work_order_status_history.py), and its
    payment/settlement snapshots (oldest first - see
    models/work_order_payment_history.py)."""

    labor: list[WorkOrderLaborLineItem]
    parts: list[WorkOrderPartLineItem]
    status_history: list[StatusHistoryItem]
    payment_history: list[PaymentHistoryItem]
