"""Read-side contracts for browsing/reporting on Work Orders.

Separate from schemas/import_work_order.py (the write-side 1C contract) on
purpose - the two evolve independently.
"""

from datetime import date, datetime
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
    phone: str | None
    payer_name: str | None
    vehicle_description: str | None
    status: str | None
    department: str | None
    # ЗаказНаряд.ВидРемонта - accident repair, scheduled maintenance,
    # warranty, etc; exact values are per-client 1C data, never hardcoded.
    repair_type: str | None
    # ЗаказНаряд.Организация - which of the client's own legal entities the
    # work order was raised under.
    organization: str | None
    # Computed at import time from the car's VIN + org/payer rules - see
    # services/internal_order_rules.py. Shown and filterable on the list;
    # AppSettings.exclude_internal_orders can additionally exclude these
    # from dashboard aggregates entirely (see work_order_query_service.py).
    is_internal: bool
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
    # Whether this ЗН has any Планировщик record (WorkshopJob or BodyCar,
    # either цех) - see services/planner_service.scheduled_work_order_ids.
    # Not a real WorkOrder column - the endpoint attaches it as a plain
    # instance attribute before validation (from_attributes just does a
    # getattr, it doesn't care that it isn't a mapped SQLAlchemy column).
    is_scheduled: bool
    # Whether WorkOrder.comment is set - drives a small "has a note" icon
    # on the list (see frontend/components/WorkOrdersTable.tsx), without
    # shipping the comment's own (possibly long) text to every row on the
    # list. Same attach-before-validate pattern as is_scheduled above - see
    # endpoints/work_orders.py's get_work_orders.
    has_comment: bool

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
    # Sum of real payment amounts (work_order_payment_events.amount) whose
    # paid_at falls in this bucket - see
    # work_order_query_service.payment_trend_summary.
    total_amount: Decimal


class PaymentTrendResponse(BaseModel):
    items: list[PaymentTrendItem]
    granularity: str  # "day" | "week" | "month"


class RevenuePaidSummaryResponse(BaseModel):
    # Of the work orders that make up the revenue figure for this period
    # (same closed_date/department/revenue_statuses filter as
    # monthly_summary), how much of their amount is actually paid
    # (sum of WorkOrder.paid_amount) - the small badge on the "Выручка за
    # период" tile.
    total_amount: Decimal


class DepartmentSummaryItem(BaseModel):
    department: str
    work_order_count: int
    total_amount: Decimal


class DepartmentSummaryResponse(BaseModel):
    items: list[DepartmentSummaryItem]


class DepartmentListResponse(BaseModel):
    departments: list[str]


class RepairTypeListResponse(BaseModel):
    repair_types: list[str]


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
    """A real status change, sourced from 1C's own
    РегистрСведений.пп_ВерсииОбъектов version log - see
    models/work_order_status_history.py. `version_number`/`status_uuid`
    are technical/traceability fields, not required for display (the UI
    shows changed_at/author/status)."""

    status: str
    changed_at: datetime
    author: str | None
    version_number: int
    status_uuid: str | None

    model_config = {"from_attributes": True}


class PaymentHistoryItem(BaseModel):
    observed_at: datetime
    deal_amount: Decimal | None
    debt_amount: Decimal | None
    paid_amount: Decimal | None
    payment_percent: Decimal | None

    model_config = {"from_attributes": True}


class PaymentEventItem(BaseModel):
    """A real, dated payment - see models/work_order_payment_event.py."""

    paid_at: datetime
    amount: Decimal
    source_document_type: str | None
    source_document_number: str | None

    model_config = {"from_attributes": True}


class InvoiceItem(BaseModel):
    """A Счёт на оплату linked to this work order - see
    models/work_order_invoice.py. `status` is derived here, not stored:
    Alpha-Auto's own status field(s) for this document type haven't been
    confirmed yet, so "paid/partial/unpaid" is computed from amount vs
    paid_amount rather than guessed."""

    external_number: str | None
    document_date: datetime | None
    amount: Decimal
    paid_amount: Decimal | None
    debt_amount: Decimal | None
    posted: bool | None
    status: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, invoice) -> "InvoiceItem":
        paid = invoice.paid_amount or Decimal("0")
        if paid <= 0:
            status = "Не оплачен"
        elif invoice.amount is not None and paid >= invoice.amount:
            status = "Оплачен"
        else:
            status = "Частично оплачен"
        return cls(
            external_number=invoice.external_number,
            document_date=invoice.document_date,
            amount=invoice.amount,
            paid_amount=invoice.paid_amount,
            debt_amount=invoice.debt_amount,
            posted=invoice.posted,
            status=status,
        )


class PlannerRecordOut(BaseModel):
    """Where this ЗН is scheduled, for the detail page's "Перейти к
    записи" button - see services/planner_service.find_planner_record."""

    kind: str  # "body" | "mechanical"
    workshop_id: UUID
    # The planner's own date window should open positioned on this day -
    # see frontend app/planner/page.tsx's `date` query param.
    date: date


class WorkOrderDetail(WorkOrderListItem):
    """Single work order's header (same fields as the list, plus `vin`)
    plus its labor (Работы) and parts (Товары) tabular-section lines, its
    status timeline (oldest first - see
    models/work_order_status_history.py), its payment/settlement snapshots
    (oldest first - see models/work_order_payment_history.py), its real
    dated payments (oldest first - see models/work_order_payment_event.py),
    and its linked Счета на оплату (newest first - see
    models/work_order_invoice.py).

    `vin` is deliberately not on WorkOrderListItem - shown on the detail
    card only, never on the list or dashboard (see
    services/internal_order_rules.py's module docstring)."""

    vin: str | None
    # Free-text staff note - see models/work_order.py's own docstring.
    # Shown/edited on the detail card only, like `vin` above.
    comment: str | None
    labor: list[WorkOrderLaborLineItem]
    parts: list[WorkOrderPartLineItem]
    status_history: list[StatusHistoryItem]
    payment_history: list[PaymentHistoryItem]
    payment_events: list[PaymentEventItem]
    invoices: list[InvoiceItem]
    planner_record: PlannerRecordOut | None


class WorkOrderCommentUpdate(BaseModel):
    comment: str | None = None
