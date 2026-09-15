"""Read API for browsing/reporting on Work Orders (table view + dashboard).

Protected by the same bearer token as the import endpoint - there is no
per-user auth system yet (see ARCHITECTURE.md), so this is a deliberate,
temporary compromise: callers (the frontend's own server, not the browser
directly) must present API_TOKEN just like the 1C integration does.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.work_order import (
    DepartmentListResponse,
    DepartmentSummaryItem,
    DepartmentSummaryResponse,
    MonthlySummaryItem,
    MonthlySummaryResponse,
    StatusHistoryItem,
    StatusSummaryItem,
    StatusSummaryResponse,
    TrendSummaryItem,
    TrendSummaryResponse,
    WorkOrderDetail,
    WorkOrderLaborLineItem,
    WorkOrderListItem,
    WorkOrderListResponse,
    WorkOrderPartLineItem,
)
from app.services.work_order_query_service import (
    delete_work_order,
    department_summary,
    get_work_order,
    list_departments,
    list_labor_lines,
    list_part_lines,
    list_status_history,
    list_work_orders,
    monthly_summary,
    status_summary,
    trend_summary,
)

router = APIRouter(tags=["work-orders"], dependencies=[Depends(verify_api_token)])


def _split_departments(departments: str | None) -> list[str] | None:
    """Query param comes in as a single comma-separated string (simplest for
    a plain query param, no repeated-key parsing needed on either side)."""
    if not departments:
        return None
    return [d.strip() for d in departments.split(",") if d.strip()]


@router.get("/work-orders", response_model=WorkOrderListResponse)
def get_work_orders(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    departments: str | None = Query(default=None, description="Comma-separated department names"),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> WorkOrderListResponse:
    items, total = list_work_orders(
        db,
        date_from=date_from,
        date_to=date_to,
        departments=_split_departments(departments),
        limit=limit,
        offset=offset,
    )
    return WorkOrderListResponse(
        items=[WorkOrderListItem.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/work-orders/departments", response_model=DepartmentListResponse)
def get_departments(db: Session = Depends(get_db)) -> DepartmentListResponse:
    return DepartmentListResponse(departments=list_departments(db))


@router.get("/work-orders/summary/monthly", response_model=MonthlySummaryResponse)
def get_monthly_summary(
    date_from: datetime | None = Query(
        default=None, description="Filters/groups by closed_date (ДатаЗакрытия), not document_date"
    ),
    date_to: datetime | None = Query(default=None),
    departments: str | None = Query(default=None, description="Comma-separated department names"),
    db: Session = Depends(get_db),
) -> MonthlySummaryResponse:
    # Revenue reporting only counts work orders in the configured "closed"
    # status(es) - an open/in-progress order's amount isn't earned revenue
    # yet. The status value itself is deployment config (Settings.
    # revenue_statuses), never hardcoded here.
    revenue_statuses = get_settings().revenue_statuses_list
    rows = monthly_summary(
        db,
        date_from=date_from,
        date_to=date_to,
        departments=_split_departments(departments),
        revenue_statuses=revenue_statuses or None,
    )
    return MonthlySummaryResponse(items=[MonthlySummaryItem(**row) for row in rows])


@router.get("/work-orders/summary/by-department", response_model=DepartmentSummaryResponse)
def get_department_summary(
    date_from: datetime | None = Query(
        default=None, description="Filters by closed_date (ДатаЗакрытия), not document_date"
    ),
    date_to: datetime | None = Query(default=None),
    departments: str | None = Query(default=None, description="Comma-separated department names"),
    db: Session = Depends(get_db),
) -> DepartmentSummaryResponse:
    revenue_statuses = get_settings().revenue_statuses_list
    rows = department_summary(
        db,
        date_from=date_from,
        date_to=date_to,
        departments=_split_departments(departments),
        revenue_statuses=revenue_statuses or None,
    )
    return DepartmentSummaryResponse(items=[DepartmentSummaryItem(**row) for row in rows])


@router.get("/work-orders/summary/by-status", response_model=StatusSummaryResponse)
def get_status_summary(
    date_from: datetime | None = Query(
        default=None, description="Filters by document_date, not closed_date"
    ),
    date_to: datetime | None = Query(default=None),
    departments: str | None = Query(default=None, description="Comma-separated department names"),
    db: Session = Depends(get_db),
) -> StatusSummaryResponse:
    # Deliberately NOT restricted to revenue_statuses - this chart exists
    # specifically to show the distribution across every status, not just
    # the ones that count as recognized revenue.
    rows = status_summary(
        db,
        date_from=date_from,
        date_to=date_to,
        departments=_split_departments(departments),
    )
    return StatusSummaryResponse(items=[StatusSummaryItem(**row) for row in rows])


@router.get("/work-orders/summary/trend", response_model=TrendSummaryResponse)
def get_trend_summary(
    date_from: datetime = Query(
        ..., description="Filters/groups by closed_date; bucket size auto-detects from the span"
    ),
    date_to: datetime = Query(...),
    departments: str | None = Query(default=None, description="Comma-separated department names"),
    granularity: str | None = Query(
        default=None,
        pattern="^(day|week|month)$",
        description="Overrides auto-detected bucket size",
    ),
    db: Session = Depends(get_db),
) -> TrendSummaryResponse:
    # Used for the dashboard's period-over-period trend chart: the caller
    # fetches this twice (current period, previous period) and relies on
    # both auto-detecting the same granularity, since the two periods are
    # the same length by construction (see app/dashboard/page.tsx).
    revenue_statuses = get_settings().revenue_statuses_list
    rows, resolved_granularity = trend_summary(
        db,
        date_from=date_from,
        date_to=date_to,
        departments=_split_departments(departments),
        revenue_statuses=revenue_statuses or None,
        granularity=granularity,
    )
    return TrendSummaryResponse(
        items=[TrendSummaryItem(**row) for row in rows], granularity=resolved_granularity
    )


@router.get("/work-orders/{work_order_id}", response_model=WorkOrderDetail)
def get_work_order_detail(work_order_id: UUID, db: Session = Depends(get_db)) -> WorkOrderDetail:
    """Header (same fields as the list row) plus labor/parts tabular-section
    lines for one work order - backs the work order detail page.

    Registered after the literal-path routes above (/departments,
    /summary/...) on purpose: FastAPI/Starlette matches routes in
    registration order, so a generic /{work_order_id} route registered
    first would swallow those literal paths as an (invalid) id instead of
    falling through to them.
    """
    work_order = get_work_order(db, work_order_id)
    if work_order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    return WorkOrderDetail(
        **WorkOrderListItem.model_validate(work_order).model_dump(),
        labor=[
            WorkOrderLaborLineItem.model_validate(line)
            for line in list_labor_lines(db, work_order_id)
        ],
        parts=[
            WorkOrderPartLineItem.model_validate(line)
            for line in list_part_lines(db, work_order_id)
        ],
        status_history=[
            StatusHistoryItem.model_validate(row) for row in list_status_history(db, work_order_id)
        ],
    )


@router.delete("/work-orders/{work_order_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_work_order(work_order_id: UUID, db: Session = Depends(get_db)) -> None:
    """Manual cleanup of a bad/test record - not part of the normal 1C flow."""
    deleted = delete_work_order(db, work_order_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
