"""Read-side queries for Work Orders - listing and monthly reporting.

Kept separate from services/import_service.py (the write path): different
concerns, different callers (this is used by the read API the frontend
calls; import_service is used by the 1C ingestion paths).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.orm import Session

from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLaborLine, WorkOrderPartLine
from app.models.work_order_status_history import WorkOrderStatusHistory


def _date_range_filters(
    column: ColumnElement, date_from: datetime | None, date_to: datetime | None
) -> list:
    filters = []
    if date_from is not None:
        filters.append(column >= date_from)
    if date_to is not None:
        filters.append(column < date_to)
    return filters


def list_work_orders(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    departments: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[WorkOrder], int]:
    """Return a page of work orders (newest first) plus the total matching count.

    The date range here is against `document_date` (browsing/listing by
    document date) - see `monthly_summary`/`department_summary` for the
    revenue-reporting queries, which filter by `closed_date` instead.
    """
    filters = _date_range_filters(WorkOrder.document_date, date_from, date_to)
    if departments:
        filters.append(WorkOrder.department.in_(departments))

    base_query = select(WorkOrder).where(*filters)

    total = db.execute(select(func.count()).select_from(base_query.subquery())).scalar_one()

    items = (
        db.execute(base_query.order_by(WorkOrder.document_date.desc()).limit(limit).offset(offset))
        .scalars()
        .all()
    )

    return list(items), total


def monthly_summary(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    departments: list[str] | None = None,
    revenue_statuses: list[str] | None = None,
) -> list[dict]:
    """Total amount and count of work orders per calendar month, oldest first.

    Grouped and date-range-filtered by `closed_date` (ДатаЗакрытия), not
    `document_date` - revenue is attributed to the month a work order was
    actually closed in, not the month it was opened/created in (a work
    order opened in June but closed in September must show up in
    September's revenue, not June's). Work orders with no closed_date yet
    (not closed) are excluded - there's no month to attribute them to.

    `revenue_statuses`, when given, additionally restricts this to only the
    status value(s) that count as recognized revenue (e.g. "Закрыт").
    Configured via Settings.revenue_statuses, not hardcoded here (see
    ARCHITECTURE.md).
    """
    filters = _date_range_filters(WorkOrder.closed_date, date_from, date_to)
    filters.append(WorkOrder.closed_date.is_not(None))
    if departments:
        filters.append(WorkOrder.department.in_(departments))
    if revenue_statuses:
        filters.append(WorkOrder.status.in_(revenue_statuses))

    month = func.date_trunc("month", WorkOrder.closed_date).label("month")

    rows = db.execute(
        select(
            month,
            func.count(WorkOrder.id).label("work_order_count"),
            func.sum(WorkOrder.amount).label("total_amount"),
        )
        .where(*filters)
        .group_by(month)
        .order_by(month)
    ).all()

    return [
        {
            "month": row.month.strftime("%Y-%m"),
            "work_order_count": row.work_order_count,
            "total_amount": row.total_amount,
        }
        for row in rows
    ]


def _bucket_starts(date_from: datetime, date_to: datetime, granularity: str) -> list[date]:
    """Every bucket start `date_trunc(granularity, closed_date)` would emit
    within [date_from, date_to) - including ones no work order closed in.

    `trend_summary` zero-fills against this list: a bucket with zero closed
    work orders must render as 0 on the trend chart, not as a missing
    point - the frontend overlays a period against its same-length
    previous-period counterpart by bucket index, so both series need the
    same, gap-free bucket count to line up.
    """
    starts: list[date] = []

    if granularity == "day":
        cursor = date_from.date()
        while datetime.combine(cursor, datetime.min.time()) < date_to:
            starts.append(cursor)
            cursor += timedelta(days=1)
    elif granularity == "week":
        # Matches Postgres date_trunc('week', ...): ISO week, Monday start.
        cursor = date_from.date() - timedelta(days=date_from.weekday())
        while datetime.combine(cursor, datetime.min.time()) < date_to:
            starts.append(cursor)
            cursor += timedelta(days=7)
    else:  # month
        year, month = date_from.year, date_from.month
        while datetime(year, month, 1) < date_to:
            starts.append(date(year, month, 1))
            month += 1
            if month > 12:
                month = 1
                year += 1

    return starts


def trend_summary(
    db: Session,
    *,
    date_from: datetime,
    date_to: datetime,
    departments: list[str] | None = None,
    revenue_statuses: list[str] | None = None,
    granularity: str | None = None,
) -> tuple[list[dict], str]:
    """Revenue/count trend bucketed by day, week, or month, oldest first.

    Same closed_date-based filtering as `monthly_summary` (grouped/filtered
    by `closed_date`, optionally restricted to `revenue_statuses`) - this
    exists to feed the dashboard's period-over-period trend chart, which
    needs finer buckets than a full month when the selected period itself is
    short (a single month selected would otherwise render as one bar).

    Granularity auto-detects from the requested period's length when not
    given explicitly: <=31 days -> day, <=92 days (~3 months) -> week,
    otherwise -> month. A caller comparing a period against its
    previous-period counterpart (identical length, by construction) gets the
    same granularity for both without having to coordinate it itself.
    """
    if granularity is None:
        span_days = (date_to - date_from).days
        if span_days <= 31:
            granularity = "day"
        elif span_days <= 92:
            granularity = "week"
        else:
            granularity = "month"
    elif granularity not in ("day", "week", "month"):
        raise ValueError(f"Unsupported granularity: {granularity!r}")

    filters = _date_range_filters(WorkOrder.closed_date, date_from, date_to)
    filters.append(WorkOrder.closed_date.is_not(None))
    if departments:
        filters.append(WorkOrder.department.in_(departments))
    if revenue_statuses:
        filters.append(WorkOrder.status.in_(revenue_statuses))

    period = func.date_trunc(granularity, WorkOrder.closed_date).label("period")

    rows = db.execute(
        select(
            period,
            func.count(WorkOrder.id).label("work_order_count"),
            func.sum(WorkOrder.amount).label("total_amount"),
        )
        .where(*filters)
        .group_by(period)
        .order_by(period)
    ).all()

    by_period = {
        row.period.date().isoformat(): {
            "period": row.period.date().isoformat(),
            "work_order_count": row.work_order_count,
            "total_amount": row.total_amount,
        }
        for row in rows
    }

    items = [
        by_period.get(
            bucket.isoformat(),
            {"period": bucket.isoformat(), "work_order_count": 0, "total_amount": Decimal("0")},
        )
        for bucket in _bucket_starts(date_from, date_to, granularity)
    ]
    return items, granularity


def department_summary(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    departments: list[str] | None = None,
    revenue_statuses: list[str] | None = None,
) -> list[dict]:
    """Total amount and count of work orders per department, for a period.

    Date-range-filtered by `closed_date`, same reasoning as
    `monthly_summary`. Work orders with no department set are grouped under
    "" and skipped - the frontend shouldn't have to special-case an empty/
    None bucket in a chart meant to compare named departments. See
    `monthly_summary` for what `revenue_statuses` does.
    """
    filters = _date_range_filters(WorkOrder.closed_date, date_from, date_to)
    filters.append(WorkOrder.closed_date.is_not(None))
    filters.append(WorkOrder.department.is_not(None))
    filters.append(WorkOrder.department != "")
    if departments:
        filters.append(WorkOrder.department.in_(departments))
    if revenue_statuses:
        filters.append(WorkOrder.status.in_(revenue_statuses))

    rows = db.execute(
        select(
            WorkOrder.department,
            func.count(WorkOrder.id).label("work_order_count"),
            func.sum(WorkOrder.amount).label("total_amount"),
        )
        .where(*filters)
        .group_by(WorkOrder.department)
        .order_by(func.sum(WorkOrder.amount).desc())
    ).all()

    return [
        {
            "department": row.department,
            "work_order_count": row.work_order_count,
            "total_amount": row.total_amount,
        }
        for row in rows
    ]


def status_summary(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    departments: list[str] | None = None,
) -> list[dict]:
    """Count and total amount of work orders per status, for a period.

    Unlike `monthly_summary`/`department_summary`, this is deliberately
    NOT restricted to `revenue_statuses` and NOT filtered/grouped by
    `closed_date` - the whole point of a status breakdown is to see the
    distribution across every status a work order can be in (open,
    in-progress, declined, closed, ...), not just the ones that count as
    recognized revenue. Restricting to closed_date would collapse this to
    ~100% "closed" and defeat the purpose. Date-range-filtered by
    `document_date` instead, matching `list_work_orders`'s own semantics
    (browsing/reporting by when the document was raised). Work orders with
    no status set are excluded, same reasoning as department_summary's
    empty-department handling.
    """
    filters = _date_range_filters(WorkOrder.document_date, date_from, date_to)
    filters.append(WorkOrder.status.is_not(None))
    filters.append(WorkOrder.status != "")
    if departments:
        filters.append(WorkOrder.department.in_(departments))

    rows = db.execute(
        select(
            WorkOrder.status,
            func.count(WorkOrder.id).label("work_order_count"),
            func.sum(WorkOrder.amount).label("total_amount"),
        )
        .where(*filters)
        .group_by(WorkOrder.status)
        .order_by(func.count(WorkOrder.id).desc())
    ).all()

    return [
        {
            "status": row.status,
            "work_order_count": row.work_order_count,
            "total_amount": row.total_amount,
        }
        for row in rows
    ]


def list_departments(db: Session) -> list[str]:
    """Distinct department values actually present in the data - never a
    hardcoded list (see ARCHITECTURE.md: department names are client data,
    not something the core knows about).
    """
    rows = db.execute(
        select(WorkOrder.department)
        .where(WorkOrder.department.is_not(None), WorkOrder.department != "")
        .distinct()
        .order_by(WorkOrder.department)
    ).all()
    return [row[0] for row in rows]


def get_work_order(db: Session, work_order_id: UUID) -> WorkOrder | None:
    """Single work order by id, or None if it doesn't exist - the header
    shown on the work order detail page (same fields as the list row)."""
    return db.get(WorkOrder, work_order_id)


def list_labor_lines(db: Session, work_order_id: UUID) -> list[WorkOrderLaborLine]:
    """A work order's "Работы" (labor) tabular-section lines."""
    rows = db.execute(
        select(WorkOrderLaborLine).where(WorkOrderLaborLine.work_order_id == work_order_id)
    ).scalars()
    return list(rows)


def list_part_lines(db: Session, work_order_id: UUID) -> list[WorkOrderPartLine]:
    """A work order's "Товары" (parts) tabular-section lines."""
    rows = db.execute(
        select(WorkOrderPartLine).where(WorkOrderPartLine.work_order_id == work_order_id)
    ).scalars()
    return list(rows)


def list_status_history(db: Session, work_order_id: UUID) -> list[WorkOrderStatusHistory]:
    """A work order's status timeline, oldest first - see
    models/work_order_status_history.py. The currently-open segment (if
    any) is the last row and has `last_seen_at is None`.
    """
    rows = db.execute(
        select(WorkOrderStatusHistory)
        .where(WorkOrderStatusHistory.work_order_id == work_order_id)
        .order_by(WorkOrderStatusHistory.first_seen_at)
    ).scalars()
    return list(rows)


def delete_work_order(db: Session, work_order_id: UUID) -> bool:
    """Delete one Work Order by id. Returns True if a row was actually deleted.

    For manual cleanup of bad/test records (e.g. smoke-test data created
    while verifying the import pipeline) - not part of the normal 1C
    ingestion flow, which only ever inserts/updates.
    """
    result = db.execute(delete(WorkOrder).where(WorkOrder.id == work_order_id))
    db.commit()
    return result.rowcount > 0
