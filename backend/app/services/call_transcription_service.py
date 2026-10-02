"""Per-call, DB-tracked transcription + YandexGPT topic classification.

A separate, additive pipeline from call_recording_service.py's own manual
"Выгрузить и расшифровать" button: that one is folder-listing-idempotent
against Yandex.Disk and archives raw audio there; this one tracks progress
directly on each telephony_calls row (CallRecord.transcript_status) and
never touches Yandex.Disk at all - SpeechKit's recognizeFileAsync takes raw
audio bytes inline in the request, so there's no need to stage the
recording anywhere between Zeon and SpeechKit. See
services/call_transcription_relay.py for the background schedule that
drives this automatically (product ask, 2026-10-02: расшифровка и разбор
темы звонка должны идти сами, без нажатия кнопки, "раз в 5-10 минут").
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import structlog
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.call_record import (
    TRANSCRIPT_STATUS_CLASSIFIED,
    TRANSCRIPT_STATUS_FAILED,
    TRANSCRIPT_STATUS_TRANSCRIBED,
    CallRecord,
)
from app.models.telephony_settings import PROVIDER_ZEON, TelephonySettings
from app.services import speechkit_client, yandexgpt_client, zeon_client
from app.services.speechkit_client import SpeechKitError, SpeechKitSettings
from app.services.yandexgpt_client import YandexGPTError, YandexGPTSettings
from app.services.zeon_client import ZeonError, ZeonSettings

# Same fixed-offset duplication as the other telephony modules - Russia has
# used a flat UTC+3 with no DST since 2014.
_MSK = timezone(timedelta(hours=3))

# A call more than this many Moscow-calendar days old is no longer worth
# transcribing/classifying (product ask, 2026-10-02: "не дёргал звонки
# старше 2 дней... старше уже не актуально ни расшифровывать ни
# отмечать") - today and yesterday only. Also keeps a one-off large
# historical backlog (e.g. right after first turning this on) from being
# worked through call-by-call for days - find_pending_calls simply never
# considers anything older.
MAX_CALL_AGE_DAYS = 1

logger = structlog.get_logger(__name__)

# Zeon's placeholder recording for a call with nothing real to hear - same
# threshold call_recording_service.py already uses for the same reason.
MIN_AUDIO_BYTES = 1024
_AUDIO_CONTAINER_BY_EXT = {".mp3": "MP3", ".wav": "WAV", ".ogg": "OGG_OPUS"}
POLL_INTERVAL_SECONDS = 5.0


class CallTranscriptionError(Exception):
    """Raised when the pipeline can't even start (missing settings)."""


def _zeon_settings(settings: TelephonySettings) -> ZeonSettings:
    if not settings.zeon_api_url or not settings.zeon_api_key:
        raise CallTranscriptionError(
            "Zeon API URL/key not configured - see Settings -> IP-телефония"
        )
    return ZeonSettings(
        api_url=settings.zeon_api_url, api_key=settings.zeon_api_key, auth=settings.zeon_auth
    )


def _speechkit_settings(settings: TelephonySettings) -> SpeechKitSettings:
    if not settings.yc_api_key:
        raise CallTranscriptionError(
            "Yandex Cloud API key (SpeechKit) not configured - see Settings -> IP-телефония"
        )
    return SpeechKitSettings(
        api_key=settings.yc_api_key,
        folder_id=settings.yc_folder_id,
        model=settings.speechkit_model,
        language=settings.speechkit_language,
    )


def _yandexgpt_settings(settings: TelephonySettings) -> YandexGPTSettings:
    if not settings.yc_api_key or not settings.yc_folder_id:
        raise CallTranscriptionError(
            "Yandex Cloud API key/folder (YandexGPT) not configured - see Settings -> IP-телефония"
        )
    return YandexGPTSettings(
        api_key=settings.yc_api_key, folder_id=settings.yc_folder_id, model=settings.yandexgpt_model
    )


def find_pending_calls(db: Session, limit: int, *, now: datetime | None = None) -> list[CallRecord]:
    """Answered calls with real talk time, from today or yesterday only
    (Moscow calendar - see MAX_CALL_AGE_DAYS), that still need
    transcribing and/or classifying - oldest first, so a backlog clears in
    call order instead of newer calls starving older ones forever. Mirrors
    telephony_stats_service.MIN_REAL_TALK_SEC's own "a real conversation"
    rule (talk_sec > 0) - a missed/zero-talk call has nothing to
    transcribe. A "failed" row (no usable recording) is never retried."""
    today_msk = (now or datetime.now(UTC)).astimezone(_MSK).date()
    min_call_date = today_msk - timedelta(days=MAX_CALL_AGE_DAYS)
    return list(
        db.scalars(
            select(CallRecord)
            .where(
                CallRecord.provider == PROVIDER_ZEON,
                CallRecord.answered.is_(True),
                CallRecord.talk_sec > 0,
                CallRecord.call_date >= min_call_date,
                or_(
                    CallRecord.transcript_status.is_(None),
                    CallRecord.transcript_status == TRANSCRIPT_STATUS_TRANSCRIBED,
                ),
            )
            .order_by(CallRecord.occurred_at)
            .limit(limit)
        )
    )


def _transcribe(
    db: Session,
    settings: TelephonySettings,
    stt_client,  # noqa: ANN001 - httpx.Client, matches speechkit_client's own untyped param style
    zeon_settings: ZeonSettings,
    stt_settings: SpeechKitSettings,
    row: CallRecord,
) -> bool:
    """Returns True once row.transcript_text is set (freshly transcribed,
    or already was) - False if this call couldn't be transcribed this
    cycle. Commits the row's progress either way, so a later retry (or the
    classify step right after, on success) always sees committed state."""
    payload = row.raw_payload or {}
    link = str(payload.get("link") or "").strip()
    if link in ("", "0"):
        row.transcript_status = TRANSCRIPT_STATUS_FAILED
        row.transcript_error = "no recording link in raw_payload"
        db.commit()
        return False

    try:
        audio = zeon_client.download_audio(zeon_settings, link, method=settings.zeon_audio_method)
    except ZeonError as exc:
        logger.error("call_transcription_download_failed", call=row.external_id, error=str(exc))
        row.transcript_error = f"download failed: {exc}"
        db.commit()
        return False

    if len(audio.data) < MIN_AUDIO_BYTES:
        row.transcript_status = TRANSCRIPT_STATUS_FAILED
        row.transcript_error = "placeholder/empty recording"
        db.commit()
        return False

    container = _AUDIO_CONTAINER_BY_EXT.get(audio.ext, "MP3")
    try:
        op_id = speechkit_client.submit(stt_client, stt_settings, audio.data, container)
        deadline = time.monotonic() + settings.speechkit_timeout_min * 60
        while not speechkit_client.is_done(stt_client, stt_settings, op_id):
            if time.monotonic() > deadline:
                raise SpeechKitError(f"timed out after {settings.speechkit_timeout_min} min")
            time.sleep(POLL_INTERVAL_SECONDS)
        responses = speechkit_client.get_result(stt_client, stt_settings, op_id)
    except SpeechKitError as exc:
        logger.error("call_transcription_speechkit_failed", call=row.external_id, error=str(exc))
        row.transcript_error = f"SpeechKit failed: {exc}"
        db.commit()
        return False

    utterances = speechkit_client.build_utterances(responses)
    text = "\n".join(f"{u['speaker']}: {u['text']}" for u in utterances).strip()
    if not text:
        row.transcript_status = TRANSCRIPT_STATUS_FAILED
        row.transcript_error = "SpeechKit returned no speech"
        db.commit()
        return False

    row.transcript_text = text
    row.transcript_status = TRANSCRIPT_STATUS_TRANSCRIBED
    row.transcript_error = None
    db.commit()
    return True


def _classify(
    db: Session,
    gpt_client,  # noqa: ANN001 - httpx.Client
    gpt_settings: YandexGPTSettings,
    row: CallRecord,
) -> bool:
    try:
        tag = yandexgpt_client.classify_topic(gpt_client, gpt_settings, row.transcript_text or "")
    except YandexGPTError as exc:
        logger.error("call_classification_failed", call=row.external_id, error=str(exc))
        row.transcript_error = f"YandexGPT failed: {exc}"
        db.commit()
        return False
    row.topic_tag = tag
    row.transcript_status = TRANSCRIPT_STATUS_CLASSIFIED
    row.transcript_error = None
    db.commit()
    return True


@dataclass
class ProcessStats:
    transcribed: int = 0
    classified: int = 0
    failed: int = 0
    errors: int = 0


def process_pending_calls(
    db: Session, settings: TelephonySettings, limit: int, *, now: datetime | None = None
) -> ProcessStats:
    """One relay cycle's worth of work - transcribes and classifies up to
    `limit` calls from today/yesterday only, oldest first. Each call
    commits its own progress as it goes, so a crash partway through never
    loses already-finished work, and a transient failure on one call just
    leaves it for the next cycle to retry (only an unusable recording is
    marked permanently "failed" - see _transcribe)."""
    stats = ProcessStats()
    rows = find_pending_calls(db, limit, now=now)
    if not rows:
        return stats

    zeon_settings = _zeon_settings(settings)
    stt_settings = _speechkit_settings(settings)
    classify = settings.classify_calls_enabled
    gpt_settings = _yandexgpt_settings(settings) if classify else None

    with speechkit_client.new_client() as stt_client, yandexgpt_client.new_client() as gpt_client:
        for row in rows:
            if row.transcript_status != TRANSCRIPT_STATUS_TRANSCRIBED:
                if not _transcribe(db, settings, stt_client, zeon_settings, stt_settings, row):
                    if row.transcript_status == TRANSCRIPT_STATUS_FAILED:
                        stats.failed += 1
                    else:
                        stats.errors += 1
                    continue
                stats.transcribed += 1

            if classify and gpt_settings is not None:
                if _classify(db, gpt_client, gpt_settings, row):
                    stats.classified += 1
                else:
                    stats.errors += 1

    logger.info(
        "call_transcription_cycle_completed",
        processed=len(rows),
        transcribed=stats.transcribed,
        classified=stats.classified,
        failed=stats.failed,
        errors=stats.errors,
    )
    return stats
