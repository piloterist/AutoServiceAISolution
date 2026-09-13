"""Read-side queries for Work Orders - listing and monthly reporting.

Kept separate from services/import_service.py (the write path): different
concerns, different callers (this is used by the read API the frontend
calls; import_service is used by the 1C ingestion paths).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.work_order import WorkOrder


def list_work_orders(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[WorkOrder], int]:
    """Return a page of work orders (newest first) plus the total matching count."""
    filters = []
    if date_from is not None:
        filters.append(WorkOrder.document_date >= date_from)
    if date_to is not None:
        filters.append(WorkOrder.document_date < date_to)

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
) -> list[dict]:
    """Total amount and count of work orders per calendar month, oldest first."""
    filters = []
    if date_from is not None:
        filters.append(WorkOrder.document_date >= date_from)
    if date_to is not None:
        filters.append(WorkOrder.document_date < date_to)

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
