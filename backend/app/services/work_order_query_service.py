"""Read-side queries for Work Orders - listing and monthly reporting.

Kept separate from services/import_service.py (the write path): different
concerns, different callers (this is used by the read API the frontend
calls; import_service is used by the 1C ingestion paths).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.work_order import WorkOrder


def _date_range_filters(date_from: datetime | None, date_to: datetime | None) -> list:
    filters = []
    if date_from is not None:
        filters.append(WorkOrder.document_date >= date_from)
    if date_to is not None:
        filters.append(WorkOrder.document_date < date_to)
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
    """Return a page of work orders (newest first) plus the total matching count."""
    filters = _date_range_filters(date_from, date_to)
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
) -> list[dict]:
    """Total amount and count of work orders per calendar month, oldest first."""
    filters = _date_range_filters(date_from, date_to)
    if departments:
        filters.append(WorkOrder.department.in_(departments))

    month = func.date_trunc("month", WorkOrder.document_date).label("month")

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


def department_summary(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    departments: list[str] | None = None,
) -> list[dict]:
    """Total amount and count of work orders per department, for a period.

    Work orders with no department set are grouped under "" and skipped -
    the frontend shouldn't have to special-case an empty/None bucket in a
    chart meant to compare named departments.
    """
    filters = _date_range_filters(date_from, date_to)
    filters.append(WorkOrder.department.is_not(None))
    filters.append(WorkOrder.department != "")
    if departments:
        filters.append(WorkOrder.department.in_(departments))

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


def delete_work_order(db: Session, work_order_id: UUID) -> bool:
    """Delete one Work Order by id. Returns True if a row was actually deleted.

    For manual cleanup of bad/test records (e.g. smoke-test data created
    while verifying the import pipeline) - not part of the normal 1C
    ingestion flow, which only ever inserts/updates.
    """
    result = db.execute(delete(WorkOrder).where(WorkOrder.id == work_order_id))
    db.commit()
    return result.rowcount > 0
