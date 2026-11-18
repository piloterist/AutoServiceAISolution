"""Боксы: текущее состояние, журнал событий въезда/выезда, снимки, запросы кадра.

Снимки лежат на Яндекс.Диске (disk:/Bays/<бокс>/...), тем же аккаунтом, что фото
заявок и записи звонков (см. lead_photos_service) - браузер к Диску не обращается,
картинку отдаёт наш бэкенд. Загрузка снимка best-effort: сбой Диска не должен терять
само событие (как и для фото заявок).

Состояние бокса выводится из интервалов занятости (BayOccupancy): подтверждённый
въезд (entry_confirmed) открывает интервал, подтверждённый выезд (exit_confirmed)
закрывает. Кандидаты и «номер замечен» состояние не меняют. Исчезновение машины из
кадра выездом не считается - его подтверждает узел на площадке.
"""

from __future__ import annotations

import base64
import binascii
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.bay import (
    EVENT_ENTRY_CONFIRMED,
    EVENT_EXIT_CONFIRMED,
    EVENT_TYPES,
    REVIEW_NEEDS,
    SNAPSHOT_DONE,
    SNAPSHOT_FAILED,
    SNAPSHOT_PENDING,
    Bay,
    BayEvent,
    BayLatestFrame,
    BayOccupancy,
    BaySnapshotRequest,
    CameraStatus,
)
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop
from app.services import telephony_settings_service, yandex_disk_client
from app.services.yandex_disk_client import YaDiskError

logger = structlog.get_logger(__name__)

DISK_BASE_PATH = "disk:/Bays"
SHOP_TZ = ZoneInfo("Europe/Moscow")  # границы «дня» в истории - по времени цеха
HISTORY_LIMIT = 500
# Запрос кадра, который узел не обработал за это время, считается проваленным.
SNAPSHOT_REQUEST_TTL = timedelta(minutes=2)
DOWNLOAD_ATTEMPTS = 3

# Российские номера используют только эти кириллические буквы; латинские
# двойники (A, B, E, K, M, H, O, P, C, T, Y, X) приводим к кириллице.
_LATIN_TO_CYRILLIC = str.maketrans(
    {
        "A": "А",
        "B": "В",
        "E": "Е",
        "K": "К",
        "M": "М",
        "H": "Н",
        "O": "О",
        "P": "Р",
        "C": "С",
        "T": "Т",
        "Y": "У",
        "X": "Х",
    }
)


class BayNotFound(Exception):
    pass


class SnapshotRequestNotFound(Exception):
    pass


class InvalidEvent(Exception):
    pass


def normalize_plate(plate: str | None) -> str | None:
    if not plate:
        return None
    cleaned = "".join(plate.split()).upper().translate(_LATIN_TO_CYRILLIC)
    return cleaned or None


# В заказ-наряде 1С номер стоит после знака «№»: «Шкода Октавиа № А612СМ777 VIN ...».
_PLATE_IN_DESCRIPTION = re.compile(
    r"№\s*([A-Za-zА-Яа-яЁё]\d{3}[A-Za-zА-Яа-яЁё]{2}\d{2,3})(?![\dA-Za-zА-Яа-я])"
)


def plate_from_description(description: str | None) -> str | None:
    """Госномер из строки автомобиля заказ-наряда (нормализованный) или None."""
    if not description:
        return None
    match = _PLATE_IN_DESCRIPTION.search(description)
    return normalize_plate(match.group(1)) if match else None


def known_plates(db: Session) -> list[dict]:
    """Номера из заказ-нарядов 1С - то, с чем узел сверяет прочитанное камерой.

    По одному номеру берётся самый свежий заказ-наряд (по дате документа). Заявки на
    ремонт сюда не попадают: ORM скрывает их, пока запрос не включит их явно.
    """
    rows = db.execute(
        select(WorkOrder.id, WorkOrder.external_number, WorkOrder.vehicle_description)
        .where(WorkOrder.vehicle_description.is_not(None))
        .order_by(WorkOrder.document_date.desc())
    ).all()
    seen: dict[str, dict] = {}
    for work_order_id, number, description in rows:
        plate = plate_from_description(description)
        if plate is not None and plate not in seen:
            seen[plate] = {
                "plate": plate,
                "work_order_id": work_order_id,
                "work_order_number": number,
            }
    return list(seen.values())


def _work_order_id_for_plate(db: Session, plate: str | None) -> uuid.UUID | None:
    if plate is None:
        return None
    for known in known_plates(db):
        if known["plate"] == plate:
            return known["work_order_id"]
    return None


def _decode_image(snapshot_base64: str | None) -> bytes | None:
    if not snapshot_base64:
        return None
    try:
        return base64.b64decode(snapshot_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidEvent("snapshot_base64 is not valid base64") from exc


def _event_path(bay_id: uuid.UUID, event_id: uuid.UUID) -> str:
    return f"{DISK_BASE_PATH}/{bay_id}/{event_id}.jpg"


def _upload(db: Session, bay_id: uuid.UUID, path: str, data: bytes, overwrite: bool) -> bool:
    """Best-effort upload to Yandex.Disk; False when it can't be stored."""
    token = telephony_settings_service.get_telephony_settings(db).yandex_disk_token
    if not token:
        logger.warning("bay_snapshot_storage_not_configured", bay_id=str(bay_id))
        return False
    try:
        with yandex_disk_client.new_client() as client:
            yandex_disk_client.ensure_path(client, token, DISK_BASE_PATH, str(bay_id))
            yandex_disk_client.upload(client, token, path, data, overwrite=overwrite)
    except YaDiskError as exc:
        logger.error("bay_snapshot_upload_failed", bay_id=str(bay_id), error=str(exc))
        return False
    return True


def download_snapshot(db: Session, path: str) -> bytes | None:
    token = telephony_settings_service.get_telephony_settings(db).yandex_disk_token
    if not token:
        return None
    # The Disk download link sometimes drops the connection (seen in the TEST container:
    # SSL EOF, 18 s responses) - a couple of retries make the frame show up anyway.
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with yandex_disk_client.new_client() as client:
                return yandex_disk_client.download(client, token, path)
        except (YaDiskError, httpx.HTTPError) as exc:
            logger.warning(
                "bay_snapshot_download_failed", path=path, attempt=attempt, error=str(exc)
            )
    return None


# ---- bays -------------------------------------------------------------------


def get_bay(db: Session, bay_id: uuid.UUID) -> Bay:
    bay = db.get(Bay, bay_id)
    if bay is None:
        raise BayNotFound(str(bay_id))
    return bay


def create_bay(
    db: Session, *, workshop_id: uuid.UUID, name: str, camera_code: str | None = None
) -> Bay:
    if db.get(Workshop, workshop_id) is None:
        raise BayNotFound(f"workshop {workshop_id}")
    next_order = (
        db.scalar(
            select(func.coalesce(func.max(Bay.sort_order), 0)).where(Bay.workshop_id == workshop_id)
        )
        or 0
    ) + 1
    bay = Bay(
        workshop_id=workshop_id, name=name.strip(), camera_code=camera_code, sort_order=next_order
    )
    db.add(bay)
    db.commit()
    db.refresh(bay)
    return bay


def create_default_bays(db: Session, workshop_id: uuid.UUID) -> list[Bay]:
    """«Бокс 1..N» по числу постов цеха - только если у цеха ещё нет боксов."""
    workshop = db.get(Workshop, workshop_id)
    if workshop is None:
        raise BayNotFound(f"workshop {workshop_id}")
    existing = db.scalar(
        select(func.count()).select_from(Bay).where(Bay.workshop_id == workshop_id)
    )
    if existing:
        return []
    bays = [
        Bay(workshop_id=workshop_id, name=f"Бокс {n}", sort_order=n)
        for n in range(1, workshop.posts_count + 1)
    ]
    db.add_all(bays)
    db.commit()
    return bays


def update_bay(
    db: Session,
    bay_id: uuid.UUID,
    *,
    name: str | None = None,
    camera_code: str | None = None,
    enabled: bool | None = None,
) -> Bay:
    bay = get_bay(db, bay_id)
    if name is not None:
        bay.name = name.strip()
    if camera_code is not None:
        bay.camera_code = camera_code.strip() or None
    if enabled is not None:
        bay.enabled = enabled
    db.commit()
    db.refresh(bay)
    return bay


def delete_bay(db: Session, bay_id: uuid.UUID) -> None:
    db.delete(get_bay(db, bay_id))
    db.commit()


# ---- overview ---------------------------------------------------------------


def event_out(event: BayEvent | None) -> dict | None:
    if event is None:
        return None
    return {
        "id": event.id,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "plate": event.plate,
        "ocr_confidence": event.ocr_confidence,
        "has_snapshot": event.snapshot_path is not None,
        "review_status": event.review_status,
        "source": event.source,
        "note": event.note,
    }


def _latest_event(db: Session, bay_id: uuid.UUID, event_type: str) -> BayEvent | None:
    return db.scalars(
        select(BayEvent)
        .where(
            BayEvent.bay_id == bay_id,
            BayEvent.event_type == event_type,
            # События, которые не учтены (шум), на карточке бокса не показываем.
            or_(
                BayEvent.note.is_(None),
                ~(
                    BayEvent.note.contains(IGNORED_MARK)
                    | BayEvent.note.contains(CANCELLED_EXIT_MARK)
                ),
            ),
        )
        .order_by(BayEvent.occurred_at.desc())
        .limit(1)
    ).first()


def record_heartbeat(
    db: Session, camera_code: str, *, camera_ok: bool, detail: str | None = None
) -> CameraStatus:
    """Узел на площадке жив; камера отдаёт (не отдаёт) видео. Момент смены состояния камеры
    запоминается - от него считается «камера недоступна уже N минут»."""
    now = datetime.now(UTC)
    status = db.get(CameraStatus, camera_code)
    if status is None:
        status = CameraStatus(
            camera_code=camera_code, seen_at=now, camera_ok=camera_ok, camera_ok_since=now
        )
        db.add(status)
    else:
        if status.camera_ok != camera_ok:
            status.camera_ok_since = now
        status.seen_at = now
        status.camera_ok = camera_ok
    status.detail = detail
    db.commit()
    db.refresh(status)
    return status


def list_bay_cards(db: Session, workshop_id: uuid.UUID | None = None) -> list[dict]:
    query = select(Bay).order_by(Bay.workshop_id, Bay.sort_order, Bay.name)
    if workshop_id is not None:
        query = query.where(Bay.workshop_id == workshop_id)
    cards = []
    for bay in db.scalars(query):
        workshop = db.get(Workshop, bay.workshop_id)
        camera = db.get(CameraStatus, bay.camera_code) if bay.camera_code else None
        open_interval = db.scalars(
            select(BayOccupancy)
            .where(BayOccupancy.bay_id == bay.id, BayOccupancy.ended_at.is_(None))
            .order_by(BayOccupancy.started_at.desc())
            .limit(1)
        ).first()
        work_order = None
        if open_interval is None:
            state, plate, since = "free", None, None
        else:
            state = "review" if open_interval.review_status == REVIEW_NEEDS else "occupied"
            plate, since = open_interval.plate, open_interval.started_at
            entry = db.get(BayEvent, open_interval.entry_event_id)
            if entry is not None and entry.work_order_id is not None:
                work_order = db.get(WorkOrder, entry.work_order_id)
        cards.append(
            {
                "id": bay.id,
                "workshop_id": bay.workshop_id,
                "name": bay.name,
                "camera_code": bay.camera_code,
                "enabled": bay.enabled,
                "state": state,
                "plate": plate,
                "occupied_since": since,
                "work_start": workshop.start_time.isoformat() if workshop else None,
                "work_end": workshop.end_time.isoformat() if workshop else None,
                "work_days": list(workshop.working_days) if workshop else [],
                "node_seen_at": camera.seen_at if camera else None,
                "camera_ok": camera.camera_ok if camera else None,
                "camera_ok_since": camera.camera_ok_since if camera else None,
                "work_order_id": work_order.id if work_order else None,
                "work_order_number": work_order.external_number if work_order else None,
                "latest_frame_at": db.scalar(
                    select(BayLatestFrame.captured_at).where(BayLatestFrame.bay_id == bay.id)
                ),
                "last_entry": event_out(_latest_event(db, bay.id, EVENT_ENTRY_CONFIRMED)),
                "last_exit": event_out(_latest_event(db, bay.id, EVENT_EXIT_CONFIRMED)),
            }
        )
    return cards


# ---- events -----------------------------------------------------------------


# Въезд на том же боксе в течение этого срока после выезда не считается: это та же машина, у
# которой выезд зафиксировался раньше времени (опустили подъёмник, номер закрыли люди), а не
# новая. Такой выезд отменяется (интервал занятости снова открыт), а въезд не создаёт ничего.
REENTRY_GRACE = timedelta(minutes=2)
IGNORED_MARK = "не учтён"
# Выезд, отменённый, когда машина тут же вернулась в кадр (bay_planner._cancel_false_exit).
CANCELLED_EXIT_MARK = "выезд отменён"
REENTRY_NOTE = f"въезд менее чем через 2 минуты после выезда: машина не уезжала, {IGNORED_MARK}"
OCCUPIED_NOTE = f"въезд при занятом боксе без выезда: {IGNORED_MARK}"
# Въезд при занятом боксе с меньшей уверенностью номера (или тем же номером) - шум, а не новая
# машина. Уверенный въезд другого номера не отбрасываем: возможно, выезд был пропущен.
OCCUPIED_NOISE_CONFIDENCE = 0.70


def _quick_reentry_exit(db: Session, bay_id: uuid.UUID, occurred_at: datetime) -> BayEvent | None:
    previous_exit = db.scalars(
        select(BayEvent)
        .where(
            BayEvent.bay_id == bay_id,
            BayEvent.event_type == EVENT_EXIT_CONFIRMED,
            BayEvent.occurred_at <= occurred_at,
        )
        .order_by(BayEvent.occurred_at.desc())
        .limit(1)
    ).first()
    if previous_exit is not None and occurred_at - previous_exit.occurred_at <= REENTRY_GRACE:
        return previous_exit
    return None


_CONSENSUS = re.compile(r"первые 6 символов: (\d+)%, кадров: (\d+)")
# Номер, считанный стабильно на многих кадрах, - реальная машина, а не мусорное чтение.
CONSENSUS_MIN_PERCENT = 90
CONSENSUS_MIN_FRAMES = 5


def _is_confident_read(event: BayEvent) -> bool:
    match = _CONSENSUS.search(event.note or "")
    return bool(
        match
        and int(match.group(1)) >= CONSENSUS_MIN_PERCENT
        and int(match.group(2)) >= CONSENSUS_MIN_FRAMES
    )


def _is_other_known_car(db: Session, event: BayEvent, last_exit: BayEvent) -> bool:
    """Въезд сразу после выезда - другая машина, а не возврат уехавшей: у номера другой
    заказ-наряд в базе либо номер стабильно считан на многих кадрах и отличается от уехавшего.
    Заказ-наряды есть не у всех машин, поэтому одного этого признака мало."""
    if event.work_order_id is not None:
        exit_order_id = _work_order_id_for_plate(db, last_exit.plate)
        if exit_order_id is not None and exit_order_id != event.work_order_id:
            return True
    differs = (event.plate or "")[:6] != (last_exit.plate or "")[:6]
    return differs and _is_confident_read(event)


def _is_noise_while_occupied(open_interval: BayOccupancy, event: BayEvent) -> bool:
    if event.ocr_confidence is not None and float(event.ocr_confidence) < OCCUPIED_NOISE_CONFIDENCE:
        return True
    same = open_interval.plate and event.plate and open_interval.plate[:6] == event.plate[:6]
    return bool(same)


def record_event(
    db: Session,
    bay_id: uuid.UUID,
    *,
    event_type: str,
    plate: str | None = None,
    ocr_confidence=None,
    occurred_at: datetime | None = None,
    note: str | None = None,
    snapshot_base64: str | None = None,
    source: str = "auto",
    needs_review: bool = False,
) -> BayEvent:
    if event_type not in EVENT_TYPES:
        raise InvalidEvent(f"Unknown event_type: {event_type}")
    bay = get_bay(db, bay_id)
    image = _decode_image(snapshot_base64)
    occurred_at = occurred_at or datetime.now(UTC)

    event = BayEvent(
        id=uuid.uuid4(),
        bay_id=bay.id,
        event_type=event_type,
        occurred_at=occurred_at,
        plate=normalize_plate(plate),
        ocr_confidence=ocr_confidence,
        note=note,
        source=source,
        review_status=(
            "confirmed" if source == "manual" else REVIEW_NEEDS if needs_review else "auto"
        ),
    )
    skip_interval = False
    if event_type == EVENT_ENTRY_CONFIRMED:
        event.work_order_id = _work_order_id_for_plate(db, event.plate)
        # Только автоматические события: ручной ввод оператора всегда считается.
        if source == "auto":
            open_now = db.scalars(
                select(BayOccupancy)
                .where(BayOccupancy.bay_id == bay.id, BayOccupancy.ended_at.is_(None))
                .order_by(BayOccupancy.started_at.desc())
                .limit(1)
            ).first()
            reason = None
            if open_now is None:
                last_exit = _quick_reentry_exit(db, bay.id, occurred_at)
                # Въезд с номером, которому в базе соответствует ДРУГОЙ заказ-наряд, - это новая
                # машина, а не возврат уехавшей (2026-11-18: Audi уехала, через минуту заехал
                # Ford, и выезд Audi был ошибочно отменён).
                if last_exit is not None and not _is_other_known_car(db, event, last_exit):
                    reason = REENTRY_NOTE
            elif _is_noise_while_occupied(open_now, event):
                reason = OCCUPIED_NOTE
            if reason:
                skip_interval = True
                event.note = f"{event.note}; {reason}" if event.note else reason
    if image is not None:
        path = _event_path(bay.id, event.id)
        if _upload(db, bay.id, path, image, overwrite=False):
            event.snapshot_path = path
    db.add(event)
    db.flush()

    if event_type == EVENT_ENTRY_CONFIRMED:
        if not skip_interval:
            _open_interval(db, event)
    elif event_type == EVENT_EXIT_CONFIRMED:
        _close_interval(db, event)
    db.commit()
    db.refresh(event)
    return event


def _open_interval(db: Session, event: BayEvent) -> None:
    review = event.review_status
    still_open = db.scalars(
        select(BayOccupancy).where(
            BayOccupancy.bay_id == event.bay_id, BayOccupancy.ended_at.is_(None)
        )
    ).all()
    if still_open:
        # Второй въезд, пока предыдущий не закрыт: не гадаем, отправляем на проверку.
        for interval in still_open:
            interval.review_status = REVIEW_NEEDS
        review = REVIEW_NEEDS
    db.add(
        BayOccupancy(
            bay_id=event.bay_id,
            plate=event.plate,
            started_at=event.occurred_at,
            entry_event_id=event.id,
            review_status=review,
        )
    )


def _close_interval(db: Session, event: BayEvent) -> None:
    interval = db.scalars(
        select(BayOccupancy)
        .where(BayOccupancy.bay_id == event.bay_id, BayOccupancy.ended_at.is_(None))
        .order_by(BayOccupancy.started_at.desc())
        .limit(1)
    ).first()
    if interval is None:
        return  # выезд без открытого интервала: остаётся в журнале для разбора
    interval.ended_at = event.occurred_at
    interval.exit_event_id = event.id


def get_event(db: Session, event_id: uuid.UUID) -> BayEvent | None:
    return db.get(BayEvent, event_id)


def list_history(
    db: Session,
    *,
    bay_id: uuid.UUID | None = None,
    workshop_id: uuid.UUID | None = None,
    date_from: date,
    date_to: date,
) -> list[dict]:
    """Заезды (интервалы занятости) за дни [date_from, date_to] по времени цеха, свежие первыми.

    День определяется по началу заезда; заезд, который ещё идёт, считается до «сейчас».
    """
    start = datetime.combine(date_from, time.min, tzinfo=SHOP_TZ)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=SHOP_TZ)
    query = (
        select(BayOccupancy, Bay)
        .join(Bay, Bay.id == BayOccupancy.bay_id)
        .where(BayOccupancy.started_at >= start, BayOccupancy.started_at < end)
        .order_by(BayOccupancy.started_at.desc())
        .limit(HISTORY_LIMIT)
    )
    if bay_id is not None:
        query = query.where(Bay.id == bay_id)
    if workshop_id is not None:
        query = query.where(Bay.workshop_id == workshop_id)
    now = datetime.now(UTC)
    items = []
    for interval, bay in db.execute(query).all():
        entry = db.get(BayEvent, interval.entry_event_id)
        exit_event = db.get(BayEvent, interval.exit_event_id) if interval.exit_event_id else None
        work_order = (
            db.get(WorkOrder, entry.work_order_id) if entry and entry.work_order_id else None
        )
        finished = interval.ended_at or now
        items.append(
            {
                "id": interval.id,
                "bay_id": bay.id,
                "bay_name": bay.name,
                "plate": interval.plate,
                "started_at": interval.started_at,
                "ended_at": interval.ended_at,
                "duration_seconds": max(int((finished - interval.started_at).total_seconds()), 0),
                "review_status": interval.review_status,
                "entry": event_out(entry),
                "exit": event_out(exit_event),
                "work_order_id": work_order.id if work_order else None,
                "work_order_number": work_order.external_number if work_order else None,
            }
        )
    return items


# ---- последний кадр бокса (раз в минуту) --------------------------------------------------------


def set_latest_frame(db: Session, bay_id: uuid.UUID, snapshot_base64: str) -> None:
    bay = get_bay(db, bay_id)
    image = _decode_image(snapshot_base64)
    if image is None:
        raise InvalidEvent("snapshot_base64 is empty")
    frame = db.get(BayLatestFrame, bay.id)
    if frame is None:
        db.add(BayLatestFrame(bay_id=bay.id, image=image, captured_at=datetime.now(UTC)))
    else:
        frame.image = image
        frame.captured_at = datetime.now(UTC)
    db.commit()


def get_latest_frame(db: Session, bay_id: uuid.UUID) -> BayLatestFrame | None:
    return db.get(BayLatestFrame, bay_id)


# ---- «получить кадр сейчас» --------------------------------------------------


def request_snapshot(db: Session, bay_id: uuid.UUID) -> BaySnapshotRequest:
    """Создаёт запрос кадра; уже ожидающий свежий запрос бокса переиспользуется."""
    bay = get_bay(db, bay_id)
    expire_stale_requests(db)
    existing = db.scalars(
        select(BaySnapshotRequest).where(
            BaySnapshotRequest.bay_id == bay.id, BaySnapshotRequest.status == SNAPSHOT_PENDING
        )
    ).first()
    if existing is not None:
        return existing
    request = BaySnapshotRequest(bay_id=bay.id)
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def expire_stale_requests(db: Session, now: datetime | None = None) -> None:
    cutoff = (now or datetime.now(UTC)) - SNAPSHOT_REQUEST_TTL
    for request in db.scalars(
        select(BaySnapshotRequest).where(
            BaySnapshotRequest.status == SNAPSHOT_PENDING, BaySnapshotRequest.requested_at < cutoff
        )
    ):
        request.status = SNAPSHOT_FAILED
        request.completed_at = datetime.now(UTC)
    db.commit()


def pending_requests(db: Session) -> list[tuple[BaySnapshotRequest, Bay]]:
    expire_stale_requests(db)
    rows = db.execute(
        select(BaySnapshotRequest, Bay)
        .join(Bay, Bay.id == BaySnapshotRequest.bay_id)
        .where(BaySnapshotRequest.status == SNAPSHOT_PENDING)
        .order_by(BaySnapshotRequest.requested_at)
    ).all()
    return [(r, b) for r, b in rows]


def get_request(db: Session, request_id: uuid.UUID) -> BaySnapshotRequest:
    request = db.get(BaySnapshotRequest, request_id)
    if request is None:
        raise SnapshotRequestNotFound(str(request_id))
    return request


def complete_request(
    db: Session, request_id: uuid.UUID, *, snapshot_base64: str | None, failed: bool
) -> BaySnapshotRequest:
    request = get_request(db, request_id)
    image = _decode_image(snapshot_base64)
    request.completed_at = datetime.now(UTC)
    if failed or image is None:
        request.status = SNAPSHOT_FAILED
    else:
        # Only the latest live frame of a bay is worth keeping.
        for older in db.scalars(
            select(BaySnapshotRequest).where(
                BaySnapshotRequest.bay_id == request.bay_id,
                BaySnapshotRequest.id != request.id,
                BaySnapshotRequest.image.is_not(None),
            )
        ):
            older.image = None
        request.image = image
        request.status = SNAPSHOT_DONE
    db.commit()
    db.refresh(request)
    return request
