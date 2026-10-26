"""Настройки -> Финансы (статьи затрат) and Финансы -> Расходы - see
services/finance_service.py. Same bearer-token protection as the rest of the
API; the Admin-only gate for the cost-item directory sits in the Next.js
middleware (/api/admin/*), like every other Settings table."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.schemas.finance import (
    CostItemOrder,
    CostItemOut,
    CostItemWrite,
    ExpensesYearResponse,
    ExpenseUpdate,
)
from app.services import finance_import_service, finance_service
from app.services.finance_service import (
    FinanceConflict,
    FinanceError,
    FinanceInvalid,
    FinanceNotFound,
)

router = APIRouter(prefix="/finance", tags=["finance"], dependencies=[Depends(verify_api_token)])


def _http_error(exc: FinanceError) -> HTTPException:
    if isinstance(exc, FinanceNotFound):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, FinanceConflict):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, FinanceInvalid):
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:  # pragma: no cover - every subclass is handled above
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/cost-items", response_model=list[CostItemOut])
def list_cost_items(db: Session = Depends(get_db)) -> list[CostItemOut]:
    return [CostItemOut.model_validate(i) for i in finance_service.list_cost_items(db)]


@router.post("/cost-items", response_model=CostItemOut, status_code=status.HTTP_201_CREATED)
def create_cost_item(payload: CostItemWrite, db: Session = Depends(get_db)) -> CostItemOut:
    try:
        item = finance_service.create_cost_item(db, name=payload.name, is_active=payload.is_active)
    except FinanceError as exc:
        raise _http_error(exc) from exc
    return CostItemOut.model_validate(item)


# Declared before "/cost-items/{item_id}" so "order" is not read as an id.
@router.put("/cost-items/order", response_model=list[CostItemOut])
def reorder_cost_items(payload: CostItemOrder, db: Session = Depends(get_db)) -> list[CostItemOut]:
    try:
        items = finance_service.reorder_cost_items(db, payload.ids)
    except FinanceError as exc:
        raise _http_error(exc) from exc
    return [CostItemOut.model_validate(i) for i in items]


@router.put("/cost-items/{item_id}", response_model=CostItemOut)
def update_cost_item(
    item_id: uuid.UUID, payload: CostItemWrite, db: Session = Depends(get_db)
) -> CostItemOut:
    try:
        item = finance_service.update_cost_item(
            db, item_id, name=payload.name, is_active=payload.is_active
        )
    except FinanceError as exc:
        raise _http_error(exc) from exc
    return CostItemOut.model_validate(item)


@router.delete("/cost-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cost_item(item_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    try:
        finance_service.delete_cost_item(db, item_id)
    except FinanceError as exc:
        raise _http_error(exc) from exc


@router.get("/expenses", response_model=ExpensesYearResponse)
def read_expenses(year: int | None = None, db: Session = Depends(get_db)) -> ExpensesYearResponse:
    """`year` omitted defaults to the current calendar year."""
    resolved_year = year or datetime.now(UTC).year
    return ExpensesYearResponse.model_validate(finance_service.get_expenses_year(db, resolved_year))


@router.put("/expenses", status_code=status.HTTP_204_NO_CONTENT)
def write_expense(payload: ExpenseUpdate, db: Session = Depends(get_db)) -> None:
    try:
        finance_service.set_expense(
            db,
            cost_item_id=payload.cost_item_id,
            workshop_id=payload.workshop_id,
            year=payload.year,
            month=payload.month,
            amount=payload.amount,
        )
    except FinanceError as exc:
        raise _http_error(exc) from exc


@router.post("/expenses/import")
async def import_expenses(
    request: Request,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    dry_run: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> dict:
    """The P&L workbook as the raw request body (no multipart): `dry_run`
    only reports what would be loaded into that month; without it, loads it."""
    content = await request.body()
    try:
        return finance_import_service.run_import(
            db, content, year=year, month=month, apply=not dry_run
        )
    except FinanceError as exc:
        raise _http_error(exc) from exc
