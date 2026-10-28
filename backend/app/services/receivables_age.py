"""Receivables older than N days are not shown (Settings -> receivables_max_age_days).

One condition shared by every place that shows the ДЗ - the Финансы -> Дебиторская
задолженность table, the ESP (cockpit) plate and the work order list behind it - so
they always agree. A debt's age is counted exactly as the aging table does: from the
latest Счет на оплату of the work order, else from its closed date. A debt that is
more than N days old is hidden; N empty/0 = no limit.
"""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select

from app.models.work_order import WorkOrder
from app.models.work_order_invoice import WorkOrderInvoice


def max_age_days(app_settings) -> int | None:
    days = app_settings.receivables_max_age_days
    return days if days and days > 0 else None


def receivable_age_filters(days: int | None, *, today: date) -> list:
    """SQL conditions keeping only debts not older than `days` (reference date
    >= today - days; `today` is the caller's current date, the same one the aging
    table counts days from)."""
    if not days:
        return []
    cutoff = datetime.combine(today - timedelta(days=days), time.min, tzinfo=UTC)
    latest_invoice = (
        select(func.max(WorkOrderInvoice.document_date))
        .where(WorkOrderInvoice.work_order_id == WorkOrder.id)
        .scalar_subquery()
    )
    return [func.coalesce(latest_invoice, WorkOrder.closed_date) >= cutoff]
