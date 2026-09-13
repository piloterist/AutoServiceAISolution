"""Request/response contracts for the 1C -> platform work order import API."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


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
    # Not sent by 1C yet, but accepted so the API can move to a more reliable
    # external key later without a breaking contract change.
    source_key: str | None = None


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
