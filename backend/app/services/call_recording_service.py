"""Call recording export + Yandex SpeechKit transcription - a separate,
button-triggered pipeline from the stats import (see
services/telephony_import_service.py).

Ported from Zeon_AI/zeon_to_yadisk.py's process_day() (audio export) and
Zeon_AI/transcribe.py's plan_day()/transcribe_jobs() (transcription), but
built on top of our own already-imported telephony_calls rows for call
metadata (client/operator/time/talk_sec) instead of re-fetching get-calls -
the raw Zeon record each row keeps in raw_payload (see models/call_record.py)
already has everything the original script needed (`link`, `src`, `dst`)
that our own typed columns don't.

Idempotency (both stages) is folder-listing-based, exactly like the
reference scripts: list what's already on Yandex.Disk for the day before
doing any work, skip what's there by filename stem. Calling this twice for
the same day is always safe and cheap the second time - nothing here
tracks "last run" separately, per the operator's own ask ("не пыталась
повторно выгружать те звонки, которые она за сегодня уже выгрузила").

Deliberately NOT tied to services/telephony_relay.py's schedule - this is
triggered from a UI button (Settings -> IP-телефония "Выгрузить и
расшифровать"), callable several times a day or backfilled over a range.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.call_record import CallRecord
from app.models.telephony_settings import PROVIDER_ZEON, TelephonySettings
from app.services import speechkit_client, yandex_disk_client, zeon_client
from app.services.speechkit_client import SpeechKitError, SpeechKitSettings
from app.services.yandex_disk_client import YaDiskError
from app.services.zeon_client import ZeonError, ZeonSettings

logger = structlog.get_logger(__name__)

AUDIO_SUBFOLDER = "Аудио"
TEXT_SUBFOLDER = "Текст"
CLI_DATE_FORMAT = "%d.%m.%Y"

# Zeon stores a ~209-byte placeholder (a couple of empty frames) for calls
# with no real recording - too small to be worth sending to SpeechKit.
MIN_AUDIO_BYTES = 1024
MAX_IN_FLIGHT = 10
POLL_INTERVAL_SECONDS = 10.0

# Same fixed-offset duplication as the other telephony modules.
_MSK = timezone(timedelta(hours=3))

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_FILENAME_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})_([^_]+)_(.*)_to_(.*)_([^_]+)$")


class CallRecordingError(Exception):
    """Raised when the pipeline can't even start (missing/incomplete
    settings), or when a whole day's folder can't be read/created."""


def _sanitize(part: object) -> str:
    text = _INVALID_FILENAME_CHARS.sub("_", "" if part is None else str(part)).strip()
    text = text.rstrip(". ")
    return text or "unknown"


def _stem(name: str) -> str:
    return name.rsplit(".", 1)[0] if "." in name else name


def day_folder(base_path: str, day: date) -> str:
    return f"{base_path}/{day.strftime(CLI_DATE_FORMAT)}"


def audio_folder(base_path: str, day: date) -> str:
    return f"{day_folder(base_path, day)}/{AUDIO_SUBFOLDER}"


def text_folder(base_path: str, day: date) -> str:
    return f"{day_folder(base_path, day)}/{TEXT_SUBFOLDER}"


def _occurred_msk(row: CallRecord) -> datetime:
    value = row.occurred_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_MSK).replace(tzinfo=None)


def _row_key(row: CallRecord) -> str:
    return _sanitize(row.linkedid or row.external_id)


def _row_filename(row: CallRecord, ext: str) -> str:
    payload = row.raw_payload or {}
    occurred = _occurred_msk(row)
    return (
        f"{occurred:%H-%M-%S}_{_sanitize(row.call_type)}_{_sanitize(payload.get('src'))}"
        f"_to_{_sanitize(payload.get('dst'))}_{_row_key(row)}{ext}"
    )


def _call_info(row: CallRecord) -> dict:
    return {
        "date": row.call_date.isoformat(),
        "time": _occurred_msk(row).strftime("%H:%M:%S"),
        "calltype": row.call_type,
        "client": row.client,
        "operator": row.operator,
        "line": row.line,
        "wait_sec": row.wait_sec,
        "talk_sec": row.talk_sec,
        "linkedid": row.linkedid,
        "external_id": row.external_id,
    }


def _zeon_settings(settings: TelephonySettings) -> ZeonSettings:
    if not settings.zeon_api_url or not settings.zeon_api_key:
        raise CallRecordingError("Zeon API URL/key not configured - see Settings -> IP-телефония")
    return ZeonSettings(
        api_url=settings.zeon_api_url, api_key=settings.zeon_api_key, auth=settings.zeon_auth
    )


def _speechkit_settings(settings: TelephonySettings) -> SpeechKitSettings:
    if not settings.yc_api_key:
        raise CallRecordingError(
            "Yandex Cloud API key (SpeechKit) not configured - see Settings -> IP-телефония"
        )
    return SpeechKitSettings(
        api_key=settings.yc_api_key,
        folder_id=settings.yc_folder_id,
        model=settings.speechkit_model,
        language=settings.speechkit_language,
    )


def _require_yandex_disk(settings: TelephonySettings) -> None:
    if not settings.yandex_disk_token or not settings.yandex_disk_base_path:
        raise CallRecordingError(
            "Yandex.Disk token/path not configured - see Settings -> IP-телефония"
        )


def _day_rows(db: Session, day: date) -> list[CallRecord]:
    return list(
        db.scalars(
            select(CallRecord)
            .where(
                CallRecord.provider == PROVIDER_ZEON,
                CallRecord.call_date == day,
                CallRecord.answered.is_(True),
            )
            .order_by(CallRecord.occurred_at)
        )
    )


# ---------------------------------------------------------------------------
# Export (Zeon -> Yandex.Disk audio)
# ---------------------------------------------------------------------------


@dataclass
class ExportStats:
    uploaded: int = 0
    skipped_exists: int = 0
    skipped_no_record: int = 0
    skipped_same_link: int = 0
    errors: int = 0


def export_recordings(
    db: Session, settings: TelephonySettings, start_day: date, end_day: date
) -> ExportStats:
    """Downloads recordings from Zeon for every already-imported, answered
    call in [start_day, end_day] and uploads them to Yandex.Disk, skipping
    whatever's already there (by filename stem, same as the reference
    script)."""
    _require_yandex_disk(settings)
    zeon_settings = _zeon_settings(settings)
    stats = ExportStats()

    with yandex_disk_client.new_client() as disk_client:
        day = start_day
        while day <= end_day:
            _export_day(db, settings, zeon_settings, disk_client, day, stats)
            day += timedelta(days=1)
    return stats


def _export_day(
    db: Session,
    settings: TelephonySettings,
    zeon_settings: ZeonSettings,
    disk_client: httpx.Client,
    day: date,
    stats: ExportStats,
) -> None:
    rows = _day_rows(db, day)
    if not rows:
        return

    folder = audio_folder(settings.yandex_disk_base_path, day)
    try:
        existing = {
            _stem(n)
            for n in yandex_disk_client.list_names(disk_client, settings.yandex_disk_token, folder)
        }
    except YaDiskError as exc:
        logger.error("call_export_list_failed", day=day.isoformat(), folder=folder, error=str(exc))
        stats.errors += 1
        return

    folder_ready = False
    seen_links: set[str] = set()

    for row in rows:
        payload = row.raw_payload or {}
        link = str(payload.get("link") or "").strip()
        if link in ("", "0"):
            stats.skipped_no_record += 1
            continue
        if link in seen_links:
            stats.skipped_same_link += 1
            continue
        seen_links.add(link)

        name = _row_filename(row, ".mp3")
        if _stem(name) in existing:
            stats.skipped_exists += 1
            continue

        if not folder_ready:
            try:
                yandex_disk_client.ensure_path(
                    disk_client,
                    settings.yandex_disk_token,
                    settings.yandex_disk_base_path,
                    day.strftime(CLI_DATE_FORMAT),
                    AUDIO_SUBFOLDER,
                )
            except YaDiskError as exc:
                logger.error("call_export_folder_failed", day=day.isoformat(), error=str(exc))
                stats.errors += 1
                return
            folder_ready = True

        try:
            audio = zeon_client.download_audio(
                zeon_settings, link, method=settings.zeon_audio_method
            )
        except ZeonError as exc:
            logger.error("call_export_download_failed", call=row.external_id, error=str(exc))
            stats.errors += 1
            continue

        if audio.ext != ".mp3":
            name = _row_filename(row, audio.ext)
        try:
            uploaded = yandex_disk_client.upload(
                disk_client, settings.yandex_disk_token, f"{folder}/{name}", audio.data
            )
        except YaDiskError as exc:
            logger.error("call_export_upload_failed", call=row.external_id, error=str(exc))
            stats.errors += 1
            continue

        if uploaded:
            stats.uploaded += 1
        else:
            stats.skipped_exists += 1

    logger.info(
        "call_export_day_completed",
        day=day.isoformat(),
        uploaded=stats.uploaded,
        skipped_exists=stats.skipped_exists,
        errors=stats.errors,
    )


# ---------------------------------------------------------------------------
# Transcribe (Yandex.Disk audio -> SpeechKit -> Yandex.Disk transcript)
# ---------------------------------------------------------------------------


@dataclass
class TranscribeStats:
    transcribed: int = 0
    skipped_exists: int = 0
    skipped_empty: int = 0
    errors: int = 0


@dataclass
class _Job:
    name: str
    path: str
    size: int
    call: dict
    container: str
    op_id: str = ""


_AUDIO_CONTAINER_BY_EXT = {".mp3": "MP3", ".wav": "WAV", ".ogg": "OGG_OPUS"}


def transcribe_recordings(
    db: Session, settings: TelephonySettings, start_day: date, end_day: date
) -> TranscribeStats:
    """Transcribes every Аудио file on Yandex.Disk within [start_day,
    end_day] that doesn't already have a matching Текст/<name>.json,
    skipping placeholder (too-small) recordings."""
    _require_yandex_disk(settings)
    stt_settings = _speechkit_settings(settings)
    stats = TranscribeStats()

    with (
        yandex_disk_client.new_client() as disk_client,
        speechkit_client.new_client() as stt_client,
    ):
        day = start_day
        while day <= end_day:
            _transcribe_day(db, settings, stt_settings, disk_client, stt_client, day, stats)
            day += timedelta(days=1)
    return stats


def _plan_day_jobs(
    db: Session,
    settings: TelephonySettings,
    disk_client: httpx.Client,
    day: date,
    stats: TranscribeStats,
) -> list[_Job]:
    src_folder = audio_folder(settings.yandex_disk_base_path, day)
    dst_folder = text_folder(settings.yandex_disk_base_path, day)
    try:
        files = yandex_disk_client.list_files(disk_client, settings.yandex_disk_token, src_folder)
        done = {
            _stem(n)
            for n in yandex_disk_client.list_names(
                disk_client, settings.yandex_disk_token, dst_folder
            )
        }
    except YaDiskError as exc:
        logger.error("call_transcribe_list_failed", day=day.isoformat(), error=str(exc))
        stats.errors += 1
        return []

    audio = {
        n: s
        for n, s in files.items()
        if "." in n and "." + n.rsplit(".", 1)[1].lower() in _AUDIO_CONTAINER_BY_EXT
    }
    if not audio:
        return []

    rows_by_key = {_row_key(row): row for row in _day_rows(db, day)}

    jobs = []
    for name, size in sorted(audio.items()):
        if _stem(name) in done:
            stats.skipped_exists += 1
            continue
        match = _FILENAME_RE.match(_stem(name))
        key = match.group(7) if match else None
        row = rows_by_key.get(key) if key else None
        call = _call_info(row) if row is not None else {"date": day.isoformat()}
        if size < MIN_AUDIO_BYTES or (row is not None and row.talk_sec == 0):
            stats.skipped_empty += 1
            continue
        ext = "." + name.rsplit(".", 1)[1].lower()
        jobs.append(_Job(name, f"{src_folder}/{name}", size, call, _AUDIO_CONTAINER_BY_EXT[ext]))
    return jobs


def _finish_job(
    job: _Job,
    day: date,
    settings: TelephonySettings,
    disk_client: httpx.Client,
    stt_client: httpx.Client,
    stt_settings: SpeechKitSettings,
    stats: TranscribeStats,
) -> None:
    responses = speechkit_client.get_result(stt_client, stt_settings, job.op_id)
    utterances = speechkit_client.build_utterances(responses)
    doc = speechkit_client.build_document(
        call=job.call,
        audio_path=job.path,
        audio_size=job.size,
        settings=stt_settings,
        op_id=job.op_id,
        utterances=utterances,
    )
    target = f"{text_folder(settings.yandex_disk_base_path, day)}/{_stem(job.name)}.json"
    data = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        uploaded = yandex_disk_client.upload(disk_client, settings.yandex_disk_token, target, data)
    except YaDiskError as exc:
        logger.error("call_transcribe_upload_failed", file=job.name, error=str(exc))
        stats.errors += 1
        return
    if uploaded:
        stats.transcribed += 1
    else:
        stats.skipped_exists += 1


def _transcribe_day(
    db: Session,
    settings: TelephonySettings,
    stt_settings: SpeechKitSettings,
    disk_client: httpx.Client,
    stt_client: httpx.Client,
    day: date,
    stats: TranscribeStats,
) -> None:
    jobs = _plan_day_jobs(db, settings, disk_client, day, stats)
    if not jobs:
        logger.info(
            "call_transcribe_day_nothing_to_do",
            day=day.isoformat(),
            skipped_exists=stats.skipped_exists,
            skipped_empty=stats.skipped_empty,
        )
        return

    try:
        yandex_disk_client.ensure_path(
            disk_client,
            settings.yandex_disk_token,
            settings.yandex_disk_base_path,
            day.strftime(CLI_DATE_FORMAT),
            TEXT_SUBFOLDER,
        )
    except YaDiskError as exc:
        logger.error("call_transcribe_folder_failed", day=day.isoformat(), error=str(exc))
        stats.errors += len(jobs)
        return

    queue = list(jobs)
    pending: list[_Job] = []
    deadline = time.monotonic() + settings.speechkit_timeout_min * 60

    while queue or pending:
        while queue and len(pending) < MAX_IN_FLIGHT:
            job = queue.pop(0)
            try:
                audio = yandex_disk_client.download(
                    disk_client, settings.yandex_disk_token, job.path
                )
                job.op_id = speechkit_client.submit(stt_client, stt_settings, audio, job.container)
                del audio
                pending.append(job)
            except (SpeechKitError, YaDiskError) as exc:
                logger.error("call_transcribe_submit_failed", file=job.name, error=str(exc))
                stats.errors += 1

        if not pending:
            continue
        time.sleep(POLL_INTERVAL_SECONDS)
        for job in list(pending):
            try:
                if not speechkit_client.is_done(stt_client, stt_settings, job.op_id):
                    continue
                pending.remove(job)
                _finish_job(job, day, settings, disk_client, stt_client, stt_settings, stats)
            except (SpeechKitError, YaDiskError) as exc:
                if job in pending:
                    pending.remove(job)
                logger.error("call_transcribe_failed", file=job.name, error=str(exc))
                stats.errors += 1

        if pending and time.monotonic() > deadline:
            logger.error(
                "call_transcribe_timed_out",
                day=day.isoformat(),
                pending=len(pending),
                queued=len(queue),
                timeout_min=settings.speechkit_timeout_min,
            )
            stats.errors += len(pending) + len(queue)
            return

    logger.info(
        "call_transcribe_day_completed",
        day=day.isoformat(),
        transcribed=stats.transcribed,
        skipped_exists=stats.skipped_exists,
        skipped_empty=stats.skipped_empty,
        errors=stats.errors,
    )


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------


@dataclass
class CallRecordingRunResult:
    export: ExportStats
    transcribe: TranscribeStats


def export_and_transcribe(
    db: Session, settings: TelephonySettings, start_day: date, end_day: date
) -> CallRecordingRunResult:
    """ "Выгрузить и расшифровать" button - runs both stages in sequence for
    [start_day, end_day]. Transcription only runs over files the export
    stage (or a previous run) actually put on Yandex.Disk, so running this
    twice in a row is always safe and just does nothing the second time."""
    export_stats = export_recordings(db, settings, start_day, end_day)
    transcribe_stats = transcribe_recordings(db, settings, start_day, end_day)
    return CallRecordingRunResult(export=export_stats, transcribe=transcribe_stats)
