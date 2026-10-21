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


class LeadCallOut(BaseModel):
    """One call to/from a lead's own phone number - see services/
    leads_service.list_calls_for_lead. Mirrors schemas/telephony.py's
    LineCallEventOut (same underlying CallRecord fields), kept as its own
    separate type since this list isn't scoped to one line/source the way
    that one is, and doesn't carry that one's цех/"Куда звонили" columns."""

    call_id: uuid.UUID
    occurred_at: datetime
    call_type: str  # IN | OUT | LOCAL | TRANSIT - see models/call_record.py
    operator: str | None  # who answered (IN) or dialed out (OUT)
    answered: bool
    wait_sec: int
    talk_sec: int
    transcript_status: str | None
    # YandexGPT-adapted ("after processing") vs SpeechKit's raw output
    # ("before processing") - same two fields/distinction as telephony's
    # own transcript_text/transcript_text_raw.
    transcript_text: str | None
    transcript_text_raw: str | None
    topic_tag: str | None
    quality_score: int | None
    quality_review: str | None
    has_recording: bool


class LeadCallsResponse(BaseModel):
    calls: list[LeadCallOut]
