"""Normalized telephony call log, fed by a provider-specific client (first
one: services/zeon_client.py) and read by the provider-agnostic
services/telephony_stats_service.py - the same "provider-specific
fetch/normalize -> one shared contract -> generic processing" split this
product already uses for the 1C work-order import (see
schemas/import_work_order.py).

Idempotency is per-call, not per-import-batch: `(provider, external_id)` is
unique, so re-fetching an overlapping time window (the background poller
in services/telephony_relay.py always re-asks for a window wider than its
own interval, to also catch late-settling missed-call outcomes) is a plain
upsert, never a duplicate. No separate "already imported" bookkeeping
table is needed for this, unlike the old file-based design this replaced
(see project memory / chat history on 2026-09-27) - calling the provider's
API directly made that unnecessary.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CALL_TYPE_IN = "IN"
CALL_TYPE_OUT = "OUT"
CALL_TYPE_LOCAL = "LOCAL"
CALL_TYPE_TRANSIT = "TRANSIT"
CALL_TYPES = (CALL_TYPE_IN, CALL_TYPE_OUT, CALL_TYPE_LOCAL, CALL_TYPE_TRANSIT)


class CallRecord(Base):
    __tablename__ = "telephony_calls"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_telephony_calls_provider_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # "zeon" today - see models/telephony_settings.py's PROVIDER_ZEON.
    provider: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # The provider's own per-record call id (Zeon: `id`) - the real
    # idempotency key, see module docstring.
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # Zeon's `linkedid` - groups related legs/attempts of the same call
    # thread. Not unique on its own (that's external_id) - kept for the
    # future call-recording/transcription pipeline, which matches audio
    # files to calls by linkedid (see Zeon_AI/stats.py's audio_by_linkedid).
    linkedid: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Moscow-local calendar day the call happened on, per the provider's
    # own reporting convention (matches Zeon's meta.date) - stored
    # separately from occurred_at (below) so the stats page's date-range
    # filter is a plain Date comparison, not a timezone-aware truncation on
    # every query.
    call_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Precise instant, converted from the provider's naive Moscow-local
    # timestamp to UTC at import time - same reasoning/helper pattern as
    # WorkOrderPaymentEvent.paid_at (see services/import_service.py's
    # _naive_msk_to_utc).
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    call_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # Normalized to the last 10 digits (see services/zeon_client.py) -
    # comparable regardless of a leading 7/8/+7 the provider sent.
    client: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # Only meaningful for IN - the line/advertising number the client
    # called, joined against phone_sources.line_code for display.
    line: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Internal extension - who talked (IN, answered) or who dialed out (OUT).
    operator: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Extensions the call rang on but that didn't pick up (Zeon's `lost`) -
    # empty/absent when not applicable, not just for missed calls.
    rang_not_answered: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    wait_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    talk_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Whatever the provider returned for this call, kept verbatim for
    # troubleshooting/future fields - same convention as WorkOrder.raw_payload.
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CallRecord {self.provider}:{self.external_id} {self.call_type}>"
