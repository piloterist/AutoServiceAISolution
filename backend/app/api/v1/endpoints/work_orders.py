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
from app.db.session import get_db
from app.schemas.work_order import (
    DepartmentListResponse,
    DepartmentSummaryItem,
    DepartmentSummaryResponse,
    MonthlySummaryItem,
    MonthlySummaryResponse,
    WorkOrderListItem,
    WorkOrderListResponse,
)
from app.services.work_order_query_service import (
    delete_work_order,
    department_summary,
    list_departments,
    list_work_orders,
    monthly_summary,
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
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    departments: str | None = Query(default=None, description="Comma-separated department names"),
    db: Session = Depends(get_db),
) -> MonthlySummaryResponse:
    rows = monthly_summary(
        db, date_from=date_from, date_to=date_to, departments=_split_departments(departments)
    )
    return MonthlySummaryResponse(items=[MonthlySummaryItem(**row) for row in rows])


@router.get("/work-orders/summary/by-department", response_model=DepartmentSummaryResponse)
def get_department_summary(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    departments: str | None = Query(default=None, description="Comma-separated department names"),
    db: Session = Depends(get_db),
) -> DepartmentSummaryResponse:
    rows = department_summary(
        db, date_from=date_from, date_to=date_to, departments=_split_departments(departments)
    )
    return DepartmentSummaryResponse(items=[DepartmentSummaryItem(**row) for row in rows])


@router.delete("/work-orders/{work_order_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_work_order(work_order_id: UUID, db: Session = Depends(get_db)) -> None:
    """Manual cleanup of a bad/test record - not part of the normal 1C flow."""
    deleted = delete_work_order(db, work_order_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
