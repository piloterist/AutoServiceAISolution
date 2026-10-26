"""Contract for Настройки -> Финансы (cost items) and Финансы -> Расходы."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CostItemOut(BaseModel):
    id: UUID
    name: str
    is_active: bool

    model_config = {"from_attributes": True}


class CostItemWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Наименование статьи не может быть пустым")
        return value


class CostItemOrder(BaseModel):
    ids: list[UUID]


class ExpenseItemRowOut(BaseModel):
    cost_item_id: UUID
    months: list[Decimal]  # always 12, index 0 = January


class ExpenseWorkshopOut(BaseModel):
    workshop_id: UUID
    workshop_label: str
    rows: list[ExpenseItemRowOut]
    totals: list[Decimal]  # per month, across every item (active or not)


class ExpensesYearResponse(BaseModel):
    year: int
    items: list[CostItemOut]
    workshops: list[ExpenseWorkshopOut]


class ExpenseUpdate(BaseModel):
    cost_item_id: UUID
    workshop_id: UUID
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    amount: Decimal = Field(ge=0)
