"""Read/write API for the Бюджет page - see services/budget_service.py.

Same bearer-token protection as the rest of the read API - see
endpoints/settings.py's docstring for the same reasoning.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.schemas.budget import BudgetEntryUpdate, BudgetYearResponse
from app.services import budget_service

router = APIRouter(prefix="/budget", tags=["budget"], dependencies=[Depends(verify_api_token)])


@router.get("", response_model=BudgetYearResponse)
def read_budget_year(year: int | None = None, db: Session = Depends(get_db)) -> BudgetYearResponse:
    """`year` omitted defaults to the current (Moscow) calendar year."""
    resolved_year = year or datetime.now(UTC).year
    rows = budget_service.get_budget_year(db, resolved_year)
    return BudgetYearResponse(year=resolved_year, workshops=rows)


@router.put("", status_code=status.HTTP_204_NO_CONTENT)
def write_budget_value(payload: BudgetEntryUpdate, db: Session = Depends(get_db)) -> None:
    try:
        budget_service.set_budget_value(
            db,
            workshop_id=payload.workshop_id,
            year=payload.year,
            month=payload.month,
            field=payload.field,
            value=payload.value,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
