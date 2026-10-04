"""IP-телефония: connection settings, phone-source directory, connection
test, manual import trigger, and the per-source call-summary table.

Same bearer-token protection as the rest of the read API - see
endpoints/settings.py's docstring for why (the frontend's server proxies
these, the browser never holds the token).
"""

import asyncio
import math
import uuid
from datetime import date, datetime, time, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import SessionLocal, get_db
from app.schemas.telephony import (
    CallRecordingExportRequest,
    CallRecordingExportResponse,
    LineCallEventOut,
    LineCallsResponse,
    OpenMissedCallOut,
    OpenMissedCallsResponse,
    PhoneSourceOut,
    PhoneSourceWrite,
    RecomputeWorkshopsResult,
    SourceSummaryResponse,
    SourceSummaryRowOut,
    TelephonyImportRequest,
    TelephonyImportResponse,
    TelephonyPingResult,
    TelephonySettingsResponse,
    TelephonySettingsUpdate,
    WorkshopPhoneMappingOut,
    WorkshopPhoneMappingWrite,
)
from app.services import (
    admin_service,
    call_recording_service,
    call_workshop_service,
    telephony_settings_service,
    telephony_stats_service,
    zeon_client,
)
from app.services.call_recording_service import CallRecordingError
from app.services.telephony_import_service import (
    TelephonyImportError,
    import_recent,
    import_window,
    zeon_settings_from,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/telephony", tags=["telephony"], dependencies=[Depends(verify_api_token)]
)

# asyncio.create_task()'s result must be kept referenced somewhere, or the
# task can be garbage-collected mid-run once this request handler returns -
# a well-known asyncio footgun (see the "Important" note on
# asyncio.create_task in the stdlib docs). main.py's own background loops
# avoid this by living in a module-level variable for the app's whole
# lifetime; this one is per-request and short-lived, so it self-removes via
# the done callback instead.
_background_tasks: set[asyncio.Task] = set()


def _spawn_background(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


# ---- Настройки подключения ------------------------------------------------


@router.get("/settings", response_model=TelephonySettingsResponse)
def read_telephony_settings(db: Session = Depends(get_db)) -> TelephonySettingsResponse:
    return TelephonySettingsResponse.model_validate(
        telephony_settings_service.get_telephony_settings(db)
    )


@router.put("/settings", response_model=TelephonySettingsResponse)
def write_telephony_settings(
    payload: TelephonySettingsUpdate, db: Session = Depends(get_db)
) -> TelephonySettingsResponse:
    try:
        payload.validate_choices()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    settings = telephony_settings_service.update_telephony_settings(
        db,
        enabled=payload.enabled,
        zeon_api_url=payload.zeon_api_url,
        zeon_api_key=payload.zeon_api_key,
        zeon_auth=payload.zeon_auth,
        yandex_disk_token=payload.yandex_disk_token,
        yandex_disk_base_path=payload.yandex_disk_base_path,
        operator_names=payload.operator_names,
        poll_interval_minutes=payload.poll_interval_minutes,
        zeon_audio_method=payload.zeon_audio_method,
        yc_api_key=payload.yc_api_key,
        yc_folder_id=payload.yc_folder_id,
        speechkit_model=payload.speechkit_model,
        speechkit_language=payload.speechkit_language,
        speechkit_timeout_min=payload.speechkit_timeout_min,
        classify_calls_enabled=payload.classify_calls_enabled,
        yandexgpt_model=payload.yandexgpt_model,
        assess_quality_enabled=payload.assess_quality_enabled,
        transcription_poll_interval_minutes=payload.transcription_poll_interval_minutes,
        transcription_batch_size=payload.transcription_batch_size,
    )
    return TelephonySettingsResponse.model_validate(settings)


@router.post("/ping", response_model=TelephonyPingResult)
def ping_telephony_provider(db: Session = Depends(get_db)) -> TelephonyPingResult:
    """ "Проверить соединение" button - validates the currently saved
    settings actually reach the provider, without importing anything."""
    settings = telephony_settings_service.get_telephony_settings(db)
    try:
        zeon_client.ping(zeon_settings_from(settings))
    except (TelephonyImportError, zeon_client.ZeonError) as exc:
        return TelephonyPingResult(ok=False, error=str(exc))
    return TelephonyPingResult(ok=True)


@router.post("/import", response_model=TelephonyImportResponse)
def trigger_telephony_import(
    payload: TelephonyImportRequest, db: Session = Depends(get_db)
) -> TelephonyImportResponse:
    """ "Импортировать сейчас" button. With no dates, imports since the last
    scheduled window; with a date range, backfills those days (both bounds
    inclusive, Moscow-local calendar days)."""
    settings = telephony_settings_service.get_telephony_settings(db)
    try:
        if payload.start_date is None:
            # Same "2x the schedule's own window" margin as before, now
            # converted from minutes to import_recent's hours parameter
            # (unrelated unit - see telephony_relay.py's own conversion).
            interval_minutes = settings.poll_interval_minutes or 24 * 60
            lookback_hours = max(1, math.ceil(interval_minutes * 2 / 60))
            result = import_recent(db, settings, lookback_hours)
        else:
            end_date = payload.end_date or payload.start_date
            start = datetime.combine(payload.start_date, time.min)
            end = datetime.combine(end_date + timedelta(days=1), time.min)
            result = import_window(db, settings, start, end)
    except TelephonyImportError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return TelephonyImportResponse(fetched=result.fetched, upserted=result.upserted)


# ---- Источники (phone_sources) --------------------------------------------


@router.get("/sources", response_model=list[PhoneSourceOut])
def list_phone_sources(db: Session = Depends(get_db)) -> list[PhoneSourceOut]:
    return [
        PhoneSourceOut.model_validate(s) for s in telephony_settings_service.list_phone_sources(db)
    ]


@router.post("/sources", response_model=PhoneSourceOut, status_code=status.HTTP_201_CREATED)
def create_phone_source(payload: PhoneSourceWrite, db: Session = Depends(get_db)) -> PhoneSourceOut:
    try:
        payload.validate_choices()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    try:
        source = telephony_settings_service.create_phone_source(
            db,
            line_code=payload.line_code,
            name=payload.name,
            caption=payload.caption,
            group_name=payload.group_name,
            sort_order=payload.sort_order,
        )
    except Exception as exc:  # unique line_code violation
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="line_code already in use"
        ) from exc
    return PhoneSourceOut.model_validate(source)


@router.put("/sources/{source_id}", response_model=PhoneSourceOut)
def update_phone_source(
    source_id: uuid.UUID, payload: PhoneSourceWrite, db: Session = Depends(get_db)
) -> PhoneSourceOut:
    try:
        payload.validate_choices()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    try:
        source = telephony_settings_service.update_phone_source(
            db,
            source_id,
            line_code=payload.line_code,
            name=payload.name,
            caption=payload.caption,
            group_name=payload.group_name,
            sort_order=payload.sort_order,
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="line_code already in use"
        ) from exc
    if source is None:
        raise _not_found("Phone source")
    return PhoneSourceOut.model_validate(source)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_phone_source(source_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    if not telephony_settings_service.delete_phone_source(db, source_id):
        raise _not_found("Phone source")


# ---- Цех — Телефон — Добавочный (workshop_phone_mappings) ------------------


def _workshop_label_map(db: Session) -> dict[uuid.UUID, str]:
    return {
        w.id: f"{department_name} — {w.workshop_type}"
        for w, department_name in admin_service.list_workshops(db)
    }


def _mapping_out(mapping, labels: dict[uuid.UUID, str]) -> WorkshopPhoneMappingOut:
    return WorkshopPhoneMappingOut(
        id=mapping.id,
        workshop_id=mapping.workshop_id,
        workshop_label=labels.get(mapping.workshop_id, "?"),
        phone=mapping.phone,
        extension=mapping.extension,
    )


@router.get("/workshop-phones", response_model=list[WorkshopPhoneMappingOut])
def list_workshop_phone_mappings(db: Session = Depends(get_db)) -> list[WorkshopPhoneMappingOut]:
    labels = _workshop_label_map(db)
    return [
        _mapping_out(m, labels) for m in telephony_settings_service.list_workshop_phone_mappings(db)
    ]


@router.post(
    "/workshop-phones", response_model=WorkshopPhoneMappingOut, status_code=status.HTTP_201_CREATED
)
def create_workshop_phone_mapping(
    payload: WorkshopPhoneMappingWrite, db: Session = Depends(get_db)
) -> WorkshopPhoneMappingOut:
    try:
        payload.validate_choices()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    mapping = telephony_settings_service.create_workshop_phone_mapping(
        db, workshop_id=payload.workshop_id, phone=payload.phone, extension=payload.extension
    )
    return _mapping_out(mapping, _workshop_label_map(db))


@router.put("/workshop-phones/{mapping_id}", response_model=WorkshopPhoneMappingOut)
def update_workshop_phone_mapping(
    mapping_id: uuid.UUID, payload: WorkshopPhoneMappingWrite, db: Session = Depends(get_db)
) -> WorkshopPhoneMappingOut:
    try:
        payload.validate_choices()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    mapping = telephony_settings_service.update_workshop_phone_mapping(
        db,
        mapping_id,
        workshop_id=payload.workshop_id,
        phone=payload.phone,
        extension=payload.extension,
    )
    if mapping is None:
        raise _not_found("Workshop phone mapping")
    return _mapping_out(mapping, _workshop_label_map(db))


@router.delete("/workshop-phones/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workshop_phone_mapping(mapping_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    if not telephony_settings_service.delete_workshop_phone_mapping(db, mapping_id):
        raise _not_found("Workshop phone mapping")


@router.post("/workshop-phones/recompute", response_model=RecomputeWorkshopsResult)
def recompute_call_workshops(db: Session = Depends(get_db)) -> RecomputeWorkshopsResult:
    """ "Пересчитать цеха" button - re-derives workshop_id/workshop_source
    for every call against the current workshop_phone_mappings table (and
    backfills dst/exten/rang_extensions from raw_payload for any call
    imported before this feature existed - see
    call_workshop_service.recompute_all)."""
    processed = call_workshop_service.recompute_all(db)
    return RecomputeWorkshopsResult(processed=processed)


# ---- Итог по каждому источнику --------------------------------------------


@router.get("/source-summary", response_model=SourceSummaryResponse)
def source_summary(
    start_date: date | None = None, end_date: date | None = None, db: Session = Depends(get_db)
) -> SourceSummaryResponse:
    """Defaults to the current Moscow-local calendar day when no range is
    given, matching Zeon_AI/stats.py's own default reporting scope."""
    today = date.today()
    range_start = start_date or today
    range_end = end_date or today
    if range_end < range_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must not be before start_date",
        )

    phone_sources = telephony_settings_service.list_phone_sources(db)
    rows = telephony_stats_service.compute_source_summary(db, range_start, range_end, phone_sources)
    return SourceSummaryResponse(
        start_date=range_start,
        end_date=range_end,
        rows=[SourceSummaryRowOut.model_validate(row) for row in rows],
    )


@router.get("/source-summary/calls", response_model=LineCallsResponse)
def line_calls(
    line_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
) -> LineCallsResponse:
    """Row expand on the "Итог по каждому источнику" table - the
    chronological call/callback timeline for one line (see
    telephony_stats_service.list_line_calls)."""
    today = date.today()
    range_start = start_date or today
    range_end = end_date or today
    if range_end < range_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must not be before start_date",
        )

    events = telephony_stats_service.list_line_calls(db, range_start, range_end, line_code)
    workshop_labels = _workshop_label_map(db)
    return LineCallsResponse(
        line_code=line_code,
        start_date=range_start,
        end_date=range_end,
        events=[
            LineCallEventOut(
                time=event.time,
                direction=event.direction,
                role=event.role,
                client=event.client,
                operator=event.operator,
                rang_not_answered=event.rang_not_answered,
                answered=event.answered,
                wait_sec=event.wait_sec,
                talk_sec=event.talk_sec,
                topic_tag=event.topic_tag,
                transcript_text=event.transcript_text,
                quality_score=event.quality_score,
                quality_review=event.quality_review,
                workshop_label=(
                    workshop_labels.get(event.workshop_id) if event.workshop_id else None
                ),
                dst=event.dst,
                dst_extension=event.dst_extension,
                answered_phone=event.answered_phone,
            )
            for event in events
        ],
    )


@router.get("/missed-calls/open", response_model=OpenMissedCallsResponse)
def open_missed_calls(db: Session = Depends(get_db)) -> OpenMissedCallsResponse:
    """Planner's phone-icon badge (see telephony_stats_service.
    get_open_missed_calls for the resolution rules) - company-wide across
    every line, not scoped to a цех (phone lines have no цех of their own
    in this data model)."""
    calls = telephony_stats_service.get_open_missed_calls(db)
    return OpenMissedCallsResponse(
        count=len(calls),
        calls=[OpenMissedCallOut.model_validate(call) for call in calls],
    )


# ---- Выгрузка записей + расшифровка ----------------------------------------


async def _run_export_and_transcribe(start_date: date, end_date: date) -> None:
    db = SessionLocal()
    try:
        settings = telephony_settings_service.get_telephony_settings(db)
        try:
            result = await asyncio.to_thread(
                call_recording_service.export_and_transcribe, db, settings, start_date, end_date
            )
        except CallRecordingError as exc:
            logger.error(
                "call_recording_run_failed",
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                error=str(exc),
            )
            return
        logger.info(
            "call_recording_run_completed",
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            uploaded=result.export.uploaded,
            export_skipped_exists=result.export.skipped_exists,
            export_skipped_no_record=result.export.skipped_no_record,
            export_errors=result.export.errors,
            transcribed=result.transcribe.transcribed,
            transcribe_skipped_exists=result.transcribe.skipped_exists,
            transcribe_skipped_empty=result.transcribe.skipped_empty,
            transcribe_errors=result.transcribe.errors,
        )
    finally:
        db.close()


@router.post("/recordings/export", response_model=CallRecordingExportResponse)
async def trigger_call_recording_export(
    payload: CallRecordingExportRequest,
) -> CallRecordingExportResponse:
    """ "Выгрузить и расшифровать" button. Runs in the background - Zeon
    audio download plus SpeechKit transcription can take several minutes
    for a busy day (see MAX_IN_FLIGHT/POLL_INTERVAL_SECONDS in
    services/call_recording_service.py) - so this returns immediately;
    progress/results land in the backend logs and directly on Yandex.Disk.
    Safe to call again (or for an overlapping range) while a previous run
    is still in flight - both stages skip whatever's already there by
    filename, same as the reference script this was ported from.

    Declared `async def` (unlike this router's other endpoints) so it runs
    on the actual event loop rather than FastAPI's sync-endpoint worker
    thread - asyncio.create_task() requires a running loop to schedule
    against, which a plain thread doesn't have."""
    if payload.end_date < payload.start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must not be before start_date",
        )
    _spawn_background(_run_export_and_transcribe(payload.start_date, payload.end_date))
    return CallRecordingExportResponse(
        status="started", start_date=payload.start_date, end_date=payload.end_date
    )
