"""API листа «Боксы» и узла видеоконтроля на площадке - see services/bay_service.py.

Тот же bearer-токен, что и у остального API (см. endpoints/settings.py). Узел на
площадке ходит сюда исходящим HTTPS: отправляет события и снимки, раз в несколько
секунд спрашивает, не нужен ли кадр (`/snapshot-requests/pending`).
"""

import uuid
from datetime import date
from typing import Literal
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.models.bay import (
    BAY_KIND_GATE,
    EVENT_ENTRY_CONFIRMED,
    EVENT_EXIT_CONFIRMED,
    SNAPSHOT_DONE,
    Bay,
    BayOccupancy,
    BaySnapshotRequest,
)
from app.schemas.bays import (
    BayCreate,
    BayEventCreate,
    BayEventOut,
    BayHistoryItem,
    BayHistoryResponse,
    BayIssueResolveIn,
    BayIssuesResponse,
    BayIssueSummary,
    BaysResponse,
    BayStayPlateIn,
    BayUpdate,
    GateStayCreate,
    GateStayExit,
    GateStayOut,
    GateStaysResponse,
    GateStayUpdate,
    HeartbeatIn,
    KnownPlatesResponse,
    LatestFrameIn,
    PendingSnapshotRequestsResponse,
    SnapshotRequestOut,
    SnapshotResult,
)
from app.services import bay_planner, bay_service, gate_service

router = APIRouter(prefix="/bays", tags=["bays"], dependencies=[Depends(verify_api_token)])

_NO_STORE = {"Cache-Control": "no-store"}


def _request_out(request: BaySnapshotRequest, camera_code: str | None = None) -> SnapshotRequestOut:
    return SnapshotRequestOut(
        id=request.id,
        bay_id=request.bay_id,
        camera_code=camera_code,
        status=request.status,
        requested_at=request.requested_at,
        completed_at=request.completed_at,
    )


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "Not found")


@router.get("", response_model=BaysResponse)
def read_bays(workshop_id: uuid.UUID | None = None, db: Session = Depends(get_db)) -> BaysResponse:
    return BaysResponse(bays=bay_service.list_bay_cards(db, workshop_id))


@router.post("", response_model=BaysResponse, status_code=status.HTTP_201_CREATED)
def create_bay(payload: BayCreate, db: Session = Depends(get_db)) -> BaysResponse:
    try:
        bay_service.create_bay(
            db,
            workshop_id=payload.workshop_id,
            name=payload.name,
            camera_code=payload.camera_code,
            kind=payload.kind,
        )
    except bay_service.BayNotFound as exc:
        raise _not_found(exc) from exc
    return BaysResponse(bays=bay_service.list_bay_cards(db, payload.workshop_id))


@router.post("/defaults", response_model=BaysResponse)
def create_default_bays(workshop_id: uuid.UUID, db: Session = Depends(get_db)) -> BaysResponse:
    try:
        bay_service.create_default_bays(db, workshop_id)
    except bay_service.BayNotFound as exc:
        raise _not_found(exc) from exc
    return BaysResponse(bays=bay_service.list_bay_cards(db, workshop_id))


# Static paths below are declared before the /{bay_id} ones so they are not
# swallowed by the UUID path parameter.


@router.get("/gate/stays", response_model=GateStaysResponse)
def read_gate_stays(
    workshop_id: uuid.UUID | None = None,
    status_filter: Literal["inside", "all"] = Query("inside", alias="status"),
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
) -> GateStaysResponse:
    """Кузовной цех: «Сейчас в цехе» (status=inside) и история заездов за период (status=all)."""
    return GateStaysResponse(
        stays=gate_service.list_stays(
            db,
            workshop_id=workshop_id,
            inside_only=status_filter == "inside",
            date_from=date_from,
            date_to=date_to,
        )
    )


@router.post("/gate/stays", response_model=GateStayOut, status_code=status.HTTP_201_CREATED)
def create_gate_stay(payload: GateStayCreate, db: Session = Depends(get_db)) -> GateStayOut:
    """Ручной въезд: машина без номера или заезд, которого камера не увидела."""
    try:
        stay = gate_service.create_manual_stay(
            db,
            payload.bay_id,
            plate=payload.plate,
            label=payload.label,
            entered_at=payload.entered_at,
        )
    except bay_service.BayNotFound as exc:
        raise _not_found(exc) from exc
    except bay_service.InvalidEvent as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return GateStayOut(**gate_service.stay_out(db, stay))


@router.post("/gate/stays/{stay_id}/exit", response_model=GateStayOut)
def exit_gate_stay(
    stay_id: uuid.UUID, payload: GateStayExit, db: Session = Depends(get_db)
) -> GateStayOut:
    """Ручной выезд."""
    try:
        stay = gate_service.exit_stay(db, stay_id, exited_at=payload.exited_at)
    except (gate_service.StayNotFound, bay_service.BayNotFound) as exc:
        raise _not_found(exc) from exc
    except bay_service.InvalidEvent as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return GateStayOut(**gate_service.stay_out(db, stay))


@router.patch("/gate/stays/{stay_id}", response_model=GateStayOut)
def update_gate_stay(
    stay_id: uuid.UUID, payload: GateStayUpdate, db: Session = Depends(get_db)
) -> GateStayOut:
    """Поправить номер или описание машины; запись плана ищется заново."""
    try:
        stay = gate_service.update_stay(db, stay_id, plate=payload.plate, label=payload.label)
    except (gate_service.StayNotFound, bay_service.BayNotFound) as exc:
        raise _not_found(exc) from exc
    except bay_service.InvalidEvent as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return GateStayOut(**gate_service.stay_out(db, stay))


@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
def post_heartbeat(payload: HeartbeatIn, db: Session = Depends(get_db)) -> Response:
    """Узел: «я на связи, камера отдаёт/не отдаёт видео» (раз в ~30 секунд по камере)."""
    bay_service.record_heartbeat(
        db, payload.camera_code, camera_ok=payload.camera_ok, detail=payload.detail
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/issues", response_model=BayIssuesResponse)
def read_issues(
    status_filter: Literal["all", "open", "resolved"] = Query("all", alias="status"),
    db: Session = Depends(get_db),
) -> BayIssuesResponse:
    """Лист «Ошибки»: машины в боксе без заказ-наряда."""
    return BayIssuesResponse(issues=bay_planner.list_issues(db, status=status_filter))


@router.get("/issues/summary", response_model=BayIssueSummary)
def read_issue_summary(db: Session = Depends(get_db)) -> BayIssueSummary:
    """Сколько ошибок не исправлено - по этому числу вкладка «Ошибки» красная или серая."""
    return BayIssueSummary(open_count=bay_planner.count_open_issues(db))


@router.post("/issues/{issue_id}/resolve", response_model=BayIssuesResponse)
def resolve_issue(
    issue_id: uuid.UUID,
    payload: BayIssueResolveIn,
    x_actor_name: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> BayIssuesResponse:
    """«Исправлено»: управляющий отметил ошибку разобранной."""
    who = unquote(x_actor_name) if x_actor_name else "Неизвестно"
    try:
        bay_planner.resolve_issue(db, issue_id, who=who, note=payload.note)
    except bay_planner.IssueNotFound as exc:
        raise _not_found(exc) from exc
    return BayIssuesResponse(issues=bay_planner.list_issues(db, status="all"))


@router.get("/known-plates", response_model=KnownPlatesResponse)
def read_known_plates(db: Session = Depends(get_db)) -> KnownPlatesResponse:
    """Номера из заказ-нарядов 1С: узел сверяет с ними прочитанный камерой номер."""
    return KnownPlatesResponse(plates=bay_service.known_plates(db))


@router.get("/history", response_model=BayHistoryResponse)
def read_history(
    date_from: date | None = None,
    date_to: date | None = None,
    bay_id: uuid.UUID | None = None,
    workshop_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> BayHistoryResponse:
    """Заезды по дням (время цеха), свежие первыми: фото въезда и выезда, время в боксе, ЗН.
    С job_id - заезды записи планировщика (без дат)."""
    if job_id is None:
        if date_from is None or date_to is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date_from and date_to are required",
            )
        if date_to < date_from:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date_to is before date_from",
            )
    items = bay_service.list_history(
        db,
        bay_id=bay_id,
        workshop_id=workshop_id,
        date_from=date_from,
        date_to=date_to,
        job_id=job_id,
    )
    return BayHistoryResponse(items=[BayHistoryItem(**item) for item in items])


@router.patch("/stays/{occupancy_id}/plate", response_model=BayHistoryItem)
def correct_stay_plate(
    occupancy_id: uuid.UUID,
    payload: BayStayPlateIn,
    x_actor_name: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> BayHistoryItem:
    """Исправить номер заезда или отметить «машина без номера» (камера прочитала не то)."""
    who = unquote(x_actor_name) if x_actor_name else "Неизвестно"
    try:
        interval, bay = bay_planner.correct_plate(
            db, occupancy_id, plate=payload.plate, no_plate=payload.no_plate, who=who
        )
    except bay_planner.StayNotFound as exc:
        raise _not_found(exc) from exc
    except bay_planner.InvalidPlate as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return BayHistoryItem(**bay_service.history_item(db, interval, bay))


@router.get("/snapshot-requests/pending", response_model=PendingSnapshotRequestsResponse)
def read_pending_snapshot_requests(
    db: Session = Depends(get_db),
) -> PendingSnapshotRequestsResponse:
    """Опрос узла на площадке: какие кадры нужно снять прямо сейчас."""
    return PendingSnapshotRequestsResponse(
        requests=[_request_out(r, bay.camera_code) for r, bay in bay_service.pending_requests(db)]
    )


@router.get("/snapshot-requests/{request_id}", response_model=SnapshotRequestOut)
def read_snapshot_request(
    request_id: uuid.UUID, db: Session = Depends(get_db)
) -> SnapshotRequestOut:
    bay_service.expire_stale_requests(db)
    try:
        return _request_out(bay_service.get_request(db, request_id))
    except bay_service.SnapshotRequestNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/snapshot-requests/{request_id}/result", response_model=SnapshotRequestOut)
def post_snapshot_result(
    request_id: uuid.UUID, payload: SnapshotResult, db: Session = Depends(get_db)
) -> SnapshotRequestOut:
    try:
        request = bay_service.complete_request(
            db, request_id, snapshot_base64=payload.snapshot_base64, failed=payload.failed
        )
    except bay_service.SnapshotRequestNotFound as exc:
        raise _not_found(exc) from exc
    except bay_service.InvalidEvent as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _request_out(request)


@router.get("/snapshot-requests/{request_id}/image")
def read_snapshot_request_image(request_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    try:
        request = bay_service.get_request(db, request_id)
    except bay_service.SnapshotRequestNotFound as exc:
        raise _not_found(exc) from exc
    if request.status != SNAPSHOT_DONE or request.image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not ready")
    return Response(content=request.image, media_type="image/jpeg", headers=_NO_STORE)


@router.get("/events/{event_id}/snapshot")
def read_event_snapshot(event_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    event = bay_service.get_event(db, event_id)
    if event is None or not event.snapshot_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    data = bay_service.download_snapshot(db, event.snapshot_path)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    # An event's snapshot never changes, so the browser may keep it.
    return Response(
        content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"}
    )


@router.post("/{bay_id}/latest-frame", status_code=status.HTTP_204_NO_CONTENT)
def post_latest_frame(
    bay_id: uuid.UUID, payload: LatestFrameIn, db: Session = Depends(get_db)
) -> Response:
    """Узел: свежий кадр бокса (раз в минуту); предыдущий заменяется."""
    try:
        bay_service.set_latest_frame(db, bay_id, payload.snapshot_base64)
    except bay_service.BayNotFound as exc:
        raise _not_found(exc) from exc
    except bay_service.InvalidEvent as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{bay_id}/latest-frame")
def read_latest_frame(bay_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    frame = bay_service.get_latest_frame(db, bay_id)
    if frame is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No frame")
    return Response(content=frame.image, media_type="image/jpeg", headers=_NO_STORE)


@router.patch("/{bay_id}", response_model=BaysResponse)
def update_bay(
    bay_id: uuid.UUID, payload: BayUpdate, db: Session = Depends(get_db)
) -> BaysResponse:
    try:
        bay = bay_service.update_bay(
            db,
            bay_id,
            name=payload.name,
            camera_code=payload.camera_code,
            enabled=payload.enabled,
        )
    except bay_service.BayNotFound as exc:
        raise _not_found(exc) from exc
    return BaysResponse(bays=bay_service.list_bay_cards(db, bay.workshop_id))


@router.delete("/{bay_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bay(bay_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    try:
        bay_service.delete_bay(db, bay_id)
    except bay_service.BayNotFound as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{bay_id}/events", response_model=BayEventOut, status_code=status.HTTP_201_CREATED)
def create_bay_event(
    bay_id: uuid.UUID,
    payload: BayEventCreate,
    x_actor_name: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> BayEventOut:
    bay = db.get(Bay, bay_id)
    if bay is not None and bay.kind == BAY_KIND_GATE:
        # Ворота кузовного цеха: свой разбор (много машин внутри, привязка к плану кузовного).
        try:
            event = gate_service.record_pass(
                db,
                bay_id,
                event_type=payload.event_type,
                plate=payload.plate,
                ocr_confidence=payload.ocr_confidence,
                occurred_at=payload.occurred_at,
                note=payload.note,
                snapshot_base64=payload.snapshot_base64,
                source=payload.source,
                needs_review=payload.needs_review,
            )
        except bay_service.InvalidEvent as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return BayEventOut(**bay_service.event_out(event))
    try:
        event = bay_service.record_event(
            db,
            bay_id,
            event_type=payload.event_type,
            plate=payload.plate,
            ocr_confidence=payload.ocr_confidence,
            occurred_at=payload.occurred_at,
            note=payload.note,
            snapshot_base64=payload.snapshot_base64,
            source=payload.source,
            needs_review=payload.needs_review,
            actor_name=unquote(x_actor_name) if x_actor_name else None,
        )
    except bay_service.BayNotFound as exc:
        raise _not_found(exc) from exc
    except bay_service.InvalidEvent as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    # Планировщик и лист «Ошибки»: запись плана «В работе»/«Готова», ошибка без заказ-наряда.
    if event.event_type == EVENT_ENTRY_CONFIRMED:
        bay_planner.on_entry(db, event)
        paired = db.scalars(
            select(BayOccupancy).where(BayOccupancy.entry_event_id == event.id)
        ).first()
        if paired is not None and paired.exit_event_id is not None:
            exit_event = bay_service.get_event(db, paired.exit_event_id)
            if exit_event is not None:
                bay_planner.on_exit(db, exit_event)  # въезд внесён за уже записанным выездом
    elif event.event_type == EVENT_EXIT_CONFIRMED:
        bay_planner.on_exit(db, event)
    db.refresh(event)
    return BayEventOut(**bay_service.event_out(event))


@router.post(
    "/{bay_id}/snapshot-requests",
    response_model=SnapshotRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def create_snapshot_request(bay_id: uuid.UUID, db: Session = Depends(get_db)) -> SnapshotRequestOut:
    try:
        return _request_out(bay_service.request_snapshot(db, bay_id))
    except bay_service.BayNotFound as exc:
        raise _not_found(exc) from exc
