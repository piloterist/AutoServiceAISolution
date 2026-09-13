"""Request/response contracts for the 1C -> platform work order import API."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ImportLaborLineRecord(BaseModel):
    """One row of a Work Order's "Работы" (labor) tabular section."""

    operation: str | None = None
    price: Decimal | None = None
    amount: Decimal | None = None


class ImportPartLineRecord(BaseModel):
    """One row of a Work Order's "Товары" (parts) tabular section."""

    item: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None


class ImportWorkOrderRecord(BaseModel):
    """One Alpha-Auto work order as sent by the 1C export job."""

    number: str = Field(..., description="External work order number (Alpha-Auto document number)")
    date: datetime = Field(..., description="Document date")
    customer: str | None = None
    # Who actually pays - can differ from `customer` (e.g. an insurance
    # company). Optional since not every source/record will have it.
    payer: str | None = None
    car: str | None = None
    amount: Decimal
    # Plain text passthrough - no hardcoded status/department values here,
    # whatever the client's 1C sends is stored as-is (see ARCHITECTURE.md).
    status: str | None = None
    department: str | None = None
    # Not sent by 1C yet, but accepted so the API can move to a more reliable
    # external key later without a breaking contract change.
    source_key: str | None = None
    labor: list[ImportLaborLineRecord] = Field(default_factory=list)
    parts: list[ImportPartLineRecord] = Field(default_factory=list)


class ImportWorkOrdersRequest(BaseModel):
    source: str = Field(..., description='e.g. "alpha-auto"')
    branch: str | None = None
    entity: str = Field(..., description='e.g. "work_orders"')
    exported_at: datetime
    batch_id: str
    records: list[ImportWorkOrderRecord] = Field(default_factory=list)


class ImportWorkOrdersResponse(BaseModel):
    status: str
    received: int
    inserted: int
    updated: int
    batch_id: str
