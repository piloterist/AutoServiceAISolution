"""Contract for /api/v1/leads - see services/leads_service.py."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LeadsSettingsOut(BaseModel):
    enabled: bool
    stale_after_days: int
    # The token itself is never echoed back after creation - same reasoning
    # as any other write-only secret in this codebase (e.g. AUTH_SECRET).
    has_intake_token: bool

    model_config = {"from_attributes": True}


class LeadsSettingsUpdate(BaseModel):
    enabled: bool
    stale_after_days: int = Field(gt=0)


class LeadsIntakeTokenOut(BaseModel):
    """Only ever returned once, right after (re)generating it - see
    endpoints/leads.py's regenerate-token route."""

    intake_token: str


class WebsiteLeadOut(BaseModel):
    id: uuid.UUID
    source: str
    phone: str
    name: str | None
    photos: list[str] | None
    raw_payload: dict
    created_at: datetime
    status: Literal["open", "resolved", "stale"]
    # The first ЗН on this same phone created after the lead itself - see
    # services/leads_service.py's own _match_work_order docstring. Computed
    # live on every read, same as `status` above - never stored.
    matched_work_order_id: uuid.UUID | None
    matched_work_order_number: str | None


class WebsiteLeadsResponse(BaseModel):
    leads: list[WebsiteLeadOut]


class OpenLeadsResponse(BaseModel):
    count: int
    leads: list[WebsiteLeadOut]
