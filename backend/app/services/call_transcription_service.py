"""Per-call, DB-tracked transcription + YandexGPT call-topic summary.

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

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.call_record import (
    TRANSCRIPT_STATUS_CLASSIFIED,
    TRANSCRIPT_STATUS_FAILED,
    TRANSCRIPT_STATUS_SKIPPED,
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

# Standard Russian mobile/landline carrier voice-prompts heard when an
# outbound call reaches an unreachable number - SpeechKit transcribes the
# network's own announcement, not a conversation with the client, so
# scoring it (product ask, 2026-10-05: six such retries to one dead number
# all got quality_score=1, as if a human operator had mishandled a human
# caller) makes no sense. Speaker splits/order are meaningless for these -
# it's one message, SpeechKit just divides it across "speakers" and chunks
# arbitrarily (e.g. "Недоступен. Абонент не отвечает или временно.") - so
# matching is a vocabulary check (every word is one this announcement
# family could use) over a short pooled transcript, not a positional one.
_CARRIER_ANNOUNCEMENT_TEMPLATES = (
    "абонент не отвечает или временно недоступен",
    "абонент временно недоступен попробуйте позвонить позже",
    "аппарат абонента выключен или находится вне зоны действия сети",
    "набранный вами номер не обслуживается",
    "телефон абонента выключен или находится вне зоны действия сети",
)
_CARRIER_ANNOUNCEMENT_VOCABULARY = frozenset(
    word for template in _CARRIER_ANNOUNCEMENT_TEMPLATES for word in template.split()
)
# A real conversation runs far longer than this - a short, all-vocabulary
# transcript is the actual signal, not just word overlap.
_CARRIER_ANNOUNCEMENT_MAX_WORDS = 14


def _looks_like_carrier_announcement(plain_text: str) -> bool:
    words = re.sub(r"[^а-яё\s]", " ", plain_text.lower()).split()
    if not words or len(words) > _CARRIER_ANNOUNCEMENT_MAX_WORDS:
        return False
    return all(word in _CARRIER_ANNOUNCEMENT_VOCABULARY for word in words)


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
    transcribing, classifying, and/or quality-assessing - oldest first, so a
    backlog clears in call order instead of newer calls starving older ones
    forever. Mirrors telephony_stats_service.MIN_REAL_TALK_SEC's own "a real
    conversation" rule (talk_sec > 0) - a missed/zero-talk call has nothing
    to transcribe. A "failed" row (no usable recording) is never retried.

    A row already at "classified" is normally done and excluded - except
    when it still has no quality_score, which only happens if
    assess_quality_enabled was turned on after that row was already
    classified (quality assessment otherwise runs in the same pass as
    classification, before the row ever leaves "transcribed" - see
    process_pending_calls). Included unconditionally rather than gated on
    the current setting value, to keep this query simple - bounded anyway
    by MAX_CALL_AGE_DAYS, so at worst a handful of already-classified rows
    get rechecked each cycle for no real work."""
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
                    and_(
                        CallRecord.transcript_status == TRANSCRIPT_STATUS_CLASSIFIED,
                        CallRecord.quality_score.is_(None),
                    ),
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
    gpt_client,  # noqa: ANN001 - httpx.Client
    gpt_settings: YandexGPTSettings | None,
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
    raw_text = "\n".join(f"{u['speaker']}: {u['text']}" for u in utterances).strip()
    if not raw_text:
        row.transcript_status = TRANSCRIPT_STATUS_FAILED
        row.transcript_error = "SpeechKit returned no speech"
        db.commit()
        return False

    plain_text = " ".join(u["text"] for u in utterances)
    if _looks_like_carrier_announcement(plain_text):
        row.transcript_text_raw = raw_text
        row.transcript_text = raw_text
        row.transcript_status = TRANSCRIPT_STATUS_SKIPPED
        row.transcript_error = None
        db.commit()
        return False

    # Corrected by YandexGPT before it's used for anything else (topic
    # summary, quality score) or shown in the UI. Two strengths, mutually
    # exclusive, picked by TelephonySettings.transcript_rewrite_enabled:
    # the usual light touch-up (adapt_transcript - product ask, 2026-10-05:
    # raw SpeechKit output reads poorly, mis-splits speaker turns) or, when
    # that setting is on, a much more aggressive rewrite (rewrite_transcript
    # - product ask, 2026-10-07: even the light pass still left "половина
    # фраз - с ошибками или определена не тому говорящему"). Both fall back
    # to the raw text unchanged on any failure, never block on this -
    # gpt_settings is None only if none of classify_calls_enabled/
    # assess_quality_enabled/transcript_rewrite_enabled is on, which
    # already keeps this whole function from running at all (see
    # find_pending_calls), so the `else raw_text` below is just defensive.
    row.transcript_text_raw = raw_text
    if gpt_settings is None:
        row.transcript_text = raw_text
    elif settings.transcript_rewrite_enabled:
        row.transcript_text = yandexgpt_client.rewrite_transcript(
            gpt_client, gpt_settings, raw_text
        )
    else:
        row.transcript_text = yandexgpt_client.adapt_transcript(gpt_client, gpt_settings, raw_text)
    row.transcript_status = TRANSCRIPT_STATUS_TRANSCRIBED
    row.transcript_error = None
    db.commit()
    return True


def _summarize_topic(
    db: Session,
    gpt_client,  # noqa: ANN001 - httpx.Client
    gpt_settings: YandexGPTSettings,
    row: CallRecord,
) -> bool:
    try:
        summary = yandexgpt_client.summarize_call_topic(
            gpt_client, gpt_settings, row.transcript_text or ""
        )
    except YandexGPTError as exc:
        logger.error("call_topic_summary_failed", call=row.external_id, error=str(exc))
        row.transcript_error = f"YandexGPT failed: {exc}"
        db.commit()
        return False
    row.topic_tag = summary
    row.transcript_status = TRANSCRIPT_STATUS_CLASSIFIED
    row.transcript_error = None
    db.commit()
    return True


def _assess_quality(
    db: Session,
    gpt_client,  # noqa: ANN001 - httpx.Client
    gpt_settings: YandexGPTSettings,
    row: CallRecord,
) -> bool:
    try:
        assessment = yandexgpt_client.assess_call_quality(
            gpt_client, gpt_settings, row.transcript_text or ""
        )
    except YandexGPTError as exc:
        logger.error("call_quality_assessment_failed", call=row.external_id, error=str(exc))
        row.transcript_error = f"YandexGPT quality assessment failed: {exc}"
        db.commit()
        return False
    row.quality_score = assessment.score
    row.quality_review = assessment.review
    row.transcript_error = None
    db.commit()
    return True


@dataclass
class ProcessStats:
    transcribed: int = 0
    classified: int = 0
    assessed: int = 0
    failed: int = 0
    skipped: int = 0
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
    assess = settings.assess_quality_enabled
    # One shared settings object for every YandexGPT step - they use the
    # same credentials (yc_api_key/yc_folder_id/yandexgpt_model). Also
    # built when only transcript_rewrite_enabled is on, so "Преобразовывать
    # диалог" works on its own without needing classify/assess too.
    gpt_settings = (
        _yandexgpt_settings(settings)
        if (classify or assess or settings.transcript_rewrite_enabled)
        else None
    )

    with speechkit_client.new_client() as stt_client, yandexgpt_client.new_client() as gpt_client:
        for row in rows:
            # find_pending_calls can also hand back an already-"classified"
            # row (the one-off case where assess_quality_enabled was turned
            # on after that row was classified) - transcript_status is None
            # is the only state that actually still needs transcribing;
            # TRANSCRIBED/CLASSIFIED both already have a transcript.
            if row.transcript_status is None:
                if not _transcribe(
                    db,
                    settings,
                    stt_client,
                    zeon_settings,
                    stt_settings,
                    gpt_client,
                    gpt_settings,
                    row,
                ):
                    if row.transcript_status == TRANSCRIPT_STATUS_FAILED:
                        stats.failed += 1
                    elif row.transcript_status == TRANSCRIPT_STATUS_SKIPPED:
                        stats.skipped += 1
                    else:
                        stats.errors += 1
                    continue
                stats.transcribed += 1

            if (
                classify
                and gpt_settings is not None
                and row.transcript_status != TRANSCRIPT_STATUS_CLASSIFIED
            ):
                if _summarize_topic(db, gpt_client, gpt_settings, row):
                    stats.classified += 1
                else:
                    stats.errors += 1

            if assess and gpt_settings is not None and row.quality_score is None:
                if _assess_quality(db, gpt_client, gpt_settings, row):
                    stats.assessed += 1
                else:
                    stats.errors += 1

    logger.info(
        "call_transcription_cycle_completed",
        processed=len(rows),
        transcribed=stats.transcribed,
        classified=stats.classified,
        assessed=stats.assessed,
        failed=stats.failed,
        skipped=stats.skipped,
        errors=stats.errors,
    )
    return stats
