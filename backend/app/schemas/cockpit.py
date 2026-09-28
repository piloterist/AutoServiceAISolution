"""Contract for GET /api/v1/cockpit - see services/cockpit_service.py."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class GaugeScaleOut(BaseModel):
    step_millions: int
    max_millions: int
    labels_millions: list[int]
    marker_fraction: float

    model_config = {"from_attributes": True}


class GaugeReadingOut(BaseModel):
    scale: GaugeScaleOut
    needle_fraction: float
    overflow: bool
    underflow: bool

    model_config = {"from_attributes": True}


class CockpitPlanOut(BaseModel):
    total_rub: Decimal
    complete: bool
    usable: bool
    workshop_count: int

    model_config = {"from_attributes": True}


class CockpitSnapshotOut(BaseModel):
    period_start: datetime
    period_end: datetime
    timezone: str
    workshop_id: uuid.UUID | None
    workshop_label: str | None

    revenue_rub: Decimal
    nzp_rub: Decimal | None
    effective_revenue_rub: Decimal
    payments_rub: Decimal

    plan: CockpitPlanOut
    revenue_gauge: GaugeReadingOut
    payments_gauge: GaugeReadingOut

    has_unattributed_revenue: bool

    model_config = {"from_attributes": True}
