"""Read-side contracts for browsing/reporting on Work Orders.

Separate from schemas/import_work_order.py (the write-side 1C contract) on
purpose - the two evolve independently.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class WorkOrderListItem(BaseModel):
    id: UUID
    external_number: str
    document_date: datetime
    customer_name: str | None
    payer_name: str | None
    vehicle_description: str | None
    status: str | None
    department: str | None
    amount: Decimal

    model_config = {"from_attributes": True}


class WorkOrderListResponse(BaseModel):
    items: list[WorkOrderListItem]
    total: int
    limit: int
    offset: int


class MonthlySummaryItem(BaseModel):
    month: str  # "YYYY-MM"
    work_order_count: int
    total_amount: Decimal


class MonthlySummaryResponse(BaseModel):
    items: list[MonthlySummaryItem]


class DepartmentSummaryItem(BaseModel):
    department: str
    work_order_count: int
    total_amount: Decimal


class DepartmentSummaryResponse(BaseModel):
    items: list[DepartmentSummaryItem]


class DepartmentListResponse(BaseModel):
    departments: list[str]
