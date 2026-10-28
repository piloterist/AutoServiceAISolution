"""Дебиторская задолженность (ДЗ) aging report - Финансы -> Дебиторская
задолженность tab.

Row-level breakdown of exactly the work orders that make up Cockpit's own ДЗ
figure (see cockpit_service._receivables / work_order_query_service.
list_work_orders(only_receivables=True), both of which this mirrors as the
"what counts as ДЗ" filter - kept as a third small copy rather than a shared
helper, same reasoning as those two give for not sharing with each other:
a SUM, a row-filter and this per-row aging breakdown aren't the same shape).
Company-wide only (no цех scope) - product ask, 2026-10-21, didn't ask for a
workshop filter here the way Cockpit has one.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.work_order import WorkOrder
from app.models.work_order_invoice import WorkOrderInvoice
from app.schemas.receivables import (
    ReceivablesAgingResponse,
    ReceivablesAgingRow,
    ReceivablesAgingTotals,
)
from app.services.internal_order_rules import is_physical_person
from app.services.order_exclusion import (
    exclusion_filters,
    order_exclusion,
)
from app.services.receivables_age import max_age_days, receivable_age_filters
from app.services.settings_service import get_app_settings

# Duplicated per this codebase's own established convention for this
# constant (see cockpit_service.MSK, work_order_query_service._MSK, etc.) -
# Russia has used a flat UTC+3 with no DST since 2014.
_MSK = timezone(timedelta(hours=3))

AGING_BUCKET_KEYS = ["lt_10", "d10_30", "d30_60", "d60_90", "gte_90"]


def _bucket_key(days_overdue: int) -> str:
    """Aging buckets as specified by the product ask: <10, 10-30, 30-60,
    60-90, 90+ days overdue. Boundaries are the lower edge of each band
    (e.g. exactly 10 days falls in 10-30, not <10)."""
    if days_overdue < 10:
        return "lt_10"
    if days_overdue < 30:
        return "d10_30"
    if days_overdue < 60:
        return "d30_60"
    if days_overdue < 90:
        return "d60_90"
    return "gte_90"


def get_aging_report(db: Session, *, now: datetime | None = None) -> ReceivablesAgingResponse:
    """Same filter as cockpit_service._receivables (company-wide: no
    workshop/department scoping here, see module docstring), but returns
    every matching work order instead of a single sum, each bucketed by how
    many days its debt has been outstanding.

    Reference date for aging, per the product ask: the work order's own
    Счет на оплату (WorkOrderInvoice.document_date) if it has one, else its
    closed_date. A work order can in principle carry more than one invoice
    (partial billing) - the most recent invoice date is used as the one
    "when was this actually billed" reference, since an earlier invoice is
    presumably superseded/settled by a later one. In practice, as of
    2026-10-21, work_order_invoices has zero rows company-wide (1C's invoice
    export was never wired up - see cockpit_service._receivables's own
    docstring), so every row currently falls back to closed_date; the
    invoice branch is implemented for when that changes, not for current
    data.
    """
    effective_now = now or datetime.now(_MSK)

    settings = get_settings()
    app_settings = get_app_settings(db)
    revenue_statuses = settings.revenue_statuses_list

    filters = [
        WorkOrder.closed_date.is_not(None),
        WorkOrder.debt_amount > 0,
        WorkOrder.closed_without_payment.is_(False),
    ]
    if revenue_statuses:
        filters.append(WorkOrder.status.in_(revenue_statuses))
    filters.extend(exclusion_filters(order_exclusion(app_settings)))
    filters.extend(receivable_age_filters(max_age_days(app_settings), today=effective_now.date()))

    # Most recently closed first (product ask, 2026-10-21) - not the
    # overdue-aging order, just a plain browsing order for the table.
    work_orders = (
        db.execute(select(WorkOrder).where(*filters).order_by(WorkOrder.closed_date.desc()))
        .scalars()
        .all()
    )

    latest_invoice_date: dict[object, datetime] = {}
    if work_orders:
        work_order_ids = [wo.id for wo in work_orders]
        invoice_rows = db.execute(
            select(WorkOrderInvoice.work_order_id, WorkOrderInvoice.document_date).where(
                WorkOrderInvoice.work_order_id.in_(work_order_ids),
                WorkOrderInvoice.document_date.is_not(None),
            )
        ).all()
        for work_order_id, document_date in invoice_rows:
            current = latest_invoice_date.get(work_order_id)
            if current is None or document_date > current:
                latest_invoice_date[work_order_id] = document_date

    totals = dict.fromkeys(AGING_BUCKET_KEYS, Decimal("0"))
    rows: list[ReceivablesAgingRow] = []
    for wo in work_orders:
        invoice_date = latest_invoice_date.get(wo.id)
        reference_date = invoice_date or wo.closed_date
        days_overdue = max(0, (effective_now.date() - reference_date.date()).days)
        bucket = _bucket_key(days_overdue)
        debt = wo.debt_amount or Decimal("0")
        totals[bucket] += debt
        rows.append(
            ReceivablesAgingRow(
                work_order_id=wo.id,
                work_order_number=wo.external_number,
                status=wo.status,
                customer_name=wo.customer_name,
                is_individual_customer=is_physical_person(wo.customer_name),
                closed_date=wo.closed_date,
                invoice_date=invoice_date,
                reference_date=reference_date,
                days_overdue=days_overdue,
                debt_amount=debt,
                bucket=bucket,
                repair_type=wo.repair_type,
            )
        )

    return ReceivablesAgingResponse(
        as_of=effective_now,
        rows=rows,
        totals=ReceivablesAgingTotals(
            lt_10=totals["lt_10"],
            d10_30=totals["d10_30"],
            d30_60=totals["d30_60"],
            d60_90=totals["d60_90"],
            gte_90=totals["gte_90"],
            total=sum(totals.values(), Decimal("0")),
        ),
        insurance_repair_type=app_settings.insurance_repair_type,
        warranty_repair_types=app_settings.warranty_repair_types or [],
    )
