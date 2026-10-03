"""Contract for the Бюджет page - see services/budget_service.py."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class BudgetMonthOut(BaseModel):
    month: int
    plan_revenue: Decimal
    fact_revenue: Decimal
    expenses: Decimal
    profit: Decimal
    payments: Decimal
    money: Decimal

    model_config = {"from_attributes": True}


class BudgetWorkshopRowOut(BaseModel):
    workshop_id: UUID
    workshop_label: str
    months: list[BudgetMonthOut]

    model_config = {"from_attributes": True}


class BudgetYearResponse(BaseModel):
    year: int
    workshops: list[BudgetWorkshopRowOut]


class BudgetEntryUpdate(BaseModel):
    workshop_id: UUID
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    field: str
    value: Decimal
