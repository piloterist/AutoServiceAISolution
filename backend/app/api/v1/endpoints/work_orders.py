"""Read API for browsing/reporting on Work Orders (table view + dashboard).

Protected by the same bearer token as the import endpoint - there is no
per-user auth system yet (see ARCHITECTURE.md), so this is a deliberate,
temporary compromise: callers (the frontend's own server, not the browser
directly) must present API_TOKEN just like the 1C integration does.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.schemas.work_order import (
    MonthlySummaryItem,
    MonthlySummaryResponse,
    WorkOrderListItem,
    WorkOrderListResponse,
)
from app.services.work_order_query_service import list_work_orders, monthly_summary

router = APIRouter(tags=["work-orders"], dependencies=[Depends(verify_api_token)])


@router.get("/work-orders", response_model=WorkOrderListResponse)
def get_work_orders(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> WorkOrderListResponse:
    items, total = list_work_orders(
        db, date_from=date_from, date_to=date_to, limit=limit, offset=offset
    )
    return WorkOrderListResponse(
        items=[WorkOrderListItem.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/work-orders/summary/monthly", response_model=MonthlySummaryResponse)
def get_monthly_summary(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
) -> MonthlySummaryResponse:
    rows = monthly_summary(db, date_from=date_from, date_to=date_to)
    return MonthlySummaryResponse(items=[MonthlySummaryItem(**row) for row in rows])
