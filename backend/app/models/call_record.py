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

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CALL_TYPE_IN = "IN"
CALL_TYPE_OUT = "OUT"
CALL_TYPE_LOCAL = "LOCAL"
CALL_TYPE_TRANSIT = "TRANSIT"
CALL_TYPES = (CALL_TYPE_IN, CALL_TYPE_OUT, CALL_TYPE_LOCAL, CALL_TYPE_TRANSIT)

# services/call_transcription_service.py's own pipeline state - distinct
# from any Zeon-side field. NULL = not attempted yet (default for every
# existing/new row); "failed" is terminal only for a call with no usable
# recording (too short/placeholder) - a transient SpeechKit/YandexGPT error
# just leaves the row as-is so the next relay cycle retries it. "skipped" is
# also terminal: the recording transcribed fine, but it's not an actual
# conversation with the client (e.g. an outbound call to an unreachable
# number, where all SpeechKit "hears" is the carrier's own "абонент не
# отвечает или временно недоступен" announcement) - product ask,
# 2026-10-05: don't score the operator 1/10 for a robot message nobody
# could have handled differently. See
# call_transcription_service._looks_like_carrier_announcement.
TRANSCRIPT_STATUS_TRANSCRIBED = "transcribed"
TRANSCRIPT_STATUS_CLASSIFIED = "classified"
TRANSCRIPT_STATUS_FAILED = "failed"
TRANSCRIPT_STATUS_SKIPPED = "skipped"
TRANSCRIPT_STATUSES = (
    TRANSCRIPT_STATUS_TRANSCRIBED,
    TRANSCRIPT_STATUS_CLASSIFIED,
    TRANSCRIPT_STATUS_FAILED,
    TRANSCRIPT_STATUS_SKIPPED,
)

# YandexGPT's short free-text summary of what a call was about (e.g.
# "Стоимость замены колодок на Chery Tiggo 8") - see
# services/yandexgpt_client.py.summarize_call_topic. Used to be a fixed
# Кузовной/Слесарный/Не определено tag (a *цех* guess from the
# conversation), but цех is now determined from the telephony data itself
# (see services/call_workshop_service.py / workshop_id below), so this
# field was freed up to carry a plain one-line description instead (product
# ask, 2026-10-04). Deliberately NOT the same concept as WorkOrder.repair_type
# (1C's own "ВидРемонта" - insurance/warranty/etc, see models/work_order.py).
TOPIC_UNDETERMINED = "Тема не определена"

# services/call_workshop_service.py's own determination source - which rule
# (if any) assigned workshop_id below. None = not computed yet (e.g. a row
# imported before this feature existed - see that service's recompute_all).
WORKSHOP_SOURCE_LINE = "line"  # matched by dst (куда звонили)
WORKSHOP_SOURCE_OPERATOR = "operator"  # matched by exten (кто ответил / с кого звонили)
WORKSHOP_SOURCE_RING_GROUP = "ring_group"  # matched by the set of extensions that rang
WORKSHOP_SOURCE_NO_MATCH = "no_match"  # nothing in workshop_phone_mappings matched
WORKSHOP_SOURCE_MULTIPLE = "multiple_workshops"  # matched rows disagree on the workshop
WORKSHOP_SOURCE_IVR_NO_ANSWER = "ivr_no_answer"  # IVR/queue, no staff extension ever answered
WORKSHOP_SOURCES = (
    WORKSHOP_SOURCE_LINE,
    WORKSHOP_SOURCE_OPERATOR,
    WORKSHOP_SOURCE_RING_GROUP,
    WORKSHOP_SOURCE_NO_MATCH,
    WORKSHOP_SOURCE_MULTIPLE,
    WORKSHOP_SOURCE_IVR_NO_ANSWER,
)


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

    # --- Transcript + topic classification (see
    # services/call_transcription_relay.py's background loop and
    # services/call_transcription_service.py) - a separate, automatic,
    # DB-tracked pipeline from call_recording_service.py's own manual
    # Yandex.Disk export/archive button, which this doesn't touch or
    # depend on. Only ever populated for answered calls with real talk
    # time (see telephony_stats_service.MIN_REAL_TALK_SEC's own "a real
    # conversation" threshold, reused here) - a missed/zero-talk call has
    # nothing to transcribe.
    transcript_status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # The YandexGPT-adapted transcript (see services/yandexgpt_client.py's
    # adapt_transcript) - lightly corrected for recognition artifacts and
    # mis-split speaker turns (e.g. a single "Добрый день" greeting wrongly
    # cut across "Говорящий 1"/"Говорящий 2"), WITHOUT changing meaning.
    # This is what topic_tag/quality_score are computed from, and what the
    # UI shows (product ask, 2026-10-05: raw SpeechKit output read poorly).
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SpeechKit's own raw, unadapted output - kept verbatim alongside the
    # adapted version above so the two can be compared from the same row,
    # without re-paying for a second SpeechKit pass through the separate,
    # manual Yandex.Disk export (see call_recording_service.py, which
    # already archives its own copy of the raw transcript independently of
    # this column).
    transcript_text_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A short free-text summary of the call (see TOPIC_UNDETERMINED above) -
    # set only once transcript_status is "classified".
    topic_tag: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Last error message, for troubleshooting a stuck/failed row from
    # Settings - cleared again on a later successful attempt.
    transcript_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # YandexGPT's QA review of this one call (product ask, 2026-10-04) - a
    # separate opt-in step from topic_tag above (see TelephonySettings.
    # assess_quality_enabled), tracked by its own presence rather than
    # transcript_status (which only models the transcribe->classify
    # progression) - None simply means "not assessed yet (or not enabled)".
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_review: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Цех determination (see services/call_workshop_service.py) - raw
    # Zeon fields kept verbatim (not normalized - matching normalizes at
    # lookup time) specifically for this, decoupled from the pre-existing
    # `line`/`operator` above (which have their own, narrower, IN-only/
    # display-oriented semantics - see their own comments - and must keep
    # behaving exactly as before). Backfilled for already-imported rows
    # straight from `raw_payload` (confirmed present there for every call
    # already on file), no re-fetch from Zeon needed - see
    # call_workshop_service.recompute_all.
    dst: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exten: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # De-duplicated union of Zeon's `members` + `lost` (every extension the
    # call rang on, answered or not) - the "кому звонило" fallback rule.
    rang_extensions: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    workshop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workshops.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workshop_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CallRecord {self.provider}:{self.external_id} {self.call_type}>"
