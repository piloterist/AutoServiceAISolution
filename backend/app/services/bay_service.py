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
    GateStay,
)
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop
from app.services import telephony_settings_service, yandex_disk_client
from app.services.yandex_disk_client import YaDiskError

logger = structlog.get_logger(__name__)

DISK_BASE_PATH = "disk:/Bays"
# Окно, в котором узел камеры присылает кадр бокса раз в минуту: с 08:00 до 24:00 (решение
# 2026-11-20, вне часов работы цеха - иначе ночью и утром на карточке висит вчерашний кадр).
# Узел сам расширяет присланное окно на NODE_FRAME_MARGIN в обе стороны (Camera/watcher.py,
# WORK_MARGIN), поэтому отдаём окно, суженное на этот запас: на узле получится ровно 08:00-24:00.
VIDEO_FRAMES_FROM = timedelta(hours=8)
VIDEO_FRAMES_TO = timedelta(hours=24)
NODE_FRAME_MARGIN = timedelta(minutes=30)


def _clock(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:00"


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


# Заказ-наряды в этих статусах машину в боксе не объясняют: 2026-11-19 к заезду Peugeot подтянулся
# закрытый ЗН от августа 2025. Номера ищем только среди остальных (в работе, ожидание и т. д.).
INACTIVE_ORDER_STATUSES = ("Закрыт", "Отказ")


def known_plates(db: Session) -> list[dict]:
    """Номера из заказ-нарядов 1С - то, с чем узел сверяет прочитанное камерой.

    Только заказ-наряды не в статусах «Закрыт» и «Отказ» (статус не указан - тоже подходит). По
    одному номеру берётся самый свежий из них (по дате документа). Заявки на ремонт сюда не
    попадают: ORM скрывает их, пока запрос не включит их явно.
    """
    rows = db.execute(
        select(WorkOrder.id, WorkOrder.external_number, WorkOrder.vehicle_description)
        .where(WorkOrder.vehicle_description.is_not(None))
        .where(
            or_(
                WorkOrder.status.is_(None),
                WorkOrder.status.not_in(INACTIVE_ORDER_STATUSES),
            )
        )
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
    db: Session,
    *,
    workshop_id: uuid.UUID,
    name: str,
    camera_code: str | None = None,
    kind: str = "bay",
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
        workshop_id=workshop_id,
        name=name.strip(),
        camera_code=camera_code,
        sort_order=next_order,
        kind=kind,
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
        "created_at": event.created_at,
        "created_by_name": event.created_by_name,
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
            no_plate = False
        else:
            state = "review" if open_interval.review_status == REVIEW_NEEDS else "occupied"
            plate, since = open_interval.plate, open_interval.started_at
            entry = db.get(BayEvent, open_interval.entry_event_id)
            no_plate = bool(entry and entry.note and NO_PLATE_NOTE in entry.note)
            if entry is not None and entry.work_order_id is not None:
                work_order = db.get(WorkOrder, entry.work_order_id)
        cards.append(
            {
                "id": bay.id,
                "workshop_id": bay.workshop_id,
                "name": bay.name,
                "camera_code": bay.camera_code,
                "enabled": bay.enabled,
                "kind": bay.kind,
                "inside_count": (
                    db.scalar(
                        select(func.count())
                        .select_from(GateStay)
                        .where(GateStay.bay_id == bay.id, GateStay.exited_at.is_(None))
                    )
                    or 0
                ),
                "state": state,
                "plate": plate,
                "no_plate": no_plate,
                "occupied_since": since,
                # Окно присылки кадров узлом (не часы работы цеха), см. VIDEO_FRAMES_FROM.
                "work_start": _clock(VIDEO_FRAMES_FROM + NODE_FRAME_MARGIN) if workshop else None,
                "work_end": _clock(VIDEO_FRAMES_TO - NODE_FRAME_MARGIN) if workshop else None,
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
# За один день у бокса не бывает двух заездов одной машины: повторный въезд тот же машины
# цепляется к её заезду (выезд между ними был ложным), если между ними в боксе не было другой
# машины с уверенным въездом и выездом.
SAME_CAR_NOTE = f"повторный въезд той же машины за день: {IGNORED_MARK}"
OTHER_CAR_CONFIDENCE = 0.70
# Заезд, закрытый автоматически, потому что узел камеры долго не был на связи (bay_planner). Если
# тот же номер увидят при первом запуске узла, заезд продолжается, а не открывается новый.
OFFLINE_NOTE = "узел видеоконтроля не был на связи больше 3 часов: заезд закрыт автоматически"
# Заезд, у которого оператор отметил «машина без номера» (bay_planner.correct_plate): номер, что
# прочитала камера, был ложным (перекупщики гоняют машины без номеров).
NO_PLATE_NOTE = "машина без номера (отмечено вручную)"
# Другая машина между двумя въездами - только если она простояла в боксе не меньше этого: короткий
# «заезд» - ложное срабатывание (опустили подъёмник, номер закрыли), а не реальная машина.
OTHER_CAR_MIN_STAY = timedelta(minutes=10)
# Номера считаются одной машиной, если из первых 6 знаков (серия и цифры, без региона) совпадают
# хотя бы 5 на тех же позициях, то есть расходится один знак: камера путает знак (2026-11-18:
# «С151СС41» вместо «С151СА99», уверенно, на 9 кадрах, и это принимали за новую машину). 4 из 6
# мало: Audi «К279КО» и Ford «К679ОО» того же дня - разные машины, а совпадают ровно на 4.
PLATE_MATCH_MIN = 5
# Только при поиске заезда этой же машины за день (повторный въезд, между которым не было другой
# уверенной машины на 10+ минут) достаточно 4 из 6: там ошибиться в сторону «та же машина» дешевле.
SAME_DAY_PLATE_MATCH_MIN = 4


def plates_match(first: str | None, second: str | None, minimum: int = PLATE_MATCH_MIN) -> bool:
    if not first or not second:
        return False
    a, b = first[:6], second[:6]
    if a == b:
        return True
    if len(a) < 6 or len(b) < 6:
        return False
    return sum(x == y for x, y in zip(a, b, strict=True)) >= minimum


def _confident(event: BayEvent | None) -> bool:
    return (
        event is not None
        and event.ocr_confidence is not None
        and float(event.ocr_confidence) > OTHER_CAR_CONFIDENCE
    )


def same_car_interval(db: Session, event: BayEvent) -> BayOccupancy | None:
    """Закрытый заезд этой же машины в этом боксе за день события, к которому надо прицепить
    повторный въезд; None, если такого нет или между ними была другая машина (уверенно)."""
    if not event.plate:
        return None
    day_start = datetime.combine(
        event.occurred_at.astimezone(SHOP_TZ).date(), time.min, tzinfo=SHOP_TZ
    )
    offline_exits = select(BayEvent.id).where(BayEvent.note.contains(OFFLINE_NOTE))
    intervals = db.scalars(
        select(BayOccupancy)
        .where(
            BayOccupancy.bay_id == event.bay_id,
            BayOccupancy.started_at <= event.occurred_at,
            BayOccupancy.ended_at.is_not(None),
            or_(
                BayOccupancy.started_at >= day_start,
                # заезд с прошлых суток, закрытый сегодня (ложный выезд): тоже можно продолжить
                BayOccupancy.ended_at >= day_start,
                BayOccupancy.exit_event_id.in_(offline_exits),
            ),
        )
        .order_by(BayOccupancy.started_at.desc())
    ).all()

    def same_car(interval: BayOccupancy) -> bool:
        entry = db.get(BayEvent, interval.entry_event_id)
        order_id = entry.work_order_id if entry is not None else None
        if event.work_order_id is not None and order_id is not None:
            return order_id == event.work_order_id  # у обоих известен заказ-наряд: он и решает
        return plates_match(interval.plate, event.plate, SAME_DAY_PLATE_MATCH_MIN)

    prior = next((i for i in intervals if same_car(i)), None)
    if prior is None:
        return None
    if (
        prior.started_at < day_start
        and db.scalars(
            select(BayOccupancy.id).where(
                BayOccupancy.bay_id == event.bay_id,
                BayOccupancy.started_at > prior.started_at,
                BayOccupancy.started_at <= event.occurred_at,
                BayOccupancy.id != prior.id,
            )
        ).first()
    ):
        return None  # заезд прошлых суток продолжаем, только если после него в боксе никого не было
    for other in intervals:
        if other.id == prior.id or other.started_at <= prior.started_at or same_car(other):
            continue
        if other.ended_at - other.started_at < OTHER_CAR_MIN_STAY:
            continue  # слишком коротко для настоящей машины
        if _confident(db.get(BayEvent, other.entry_event_id)) and _confident(
            db.get(BayEvent, other.exit_event_id) if other.exit_event_id else None
        ):
            return None  # между въездами была другая машина
    return prior


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
    # Сравниваем с машиной, которую выезд закрыл (номер её заезда), а не с номером самого выезда:
    # у выезда он мог быть считан криво (2026-11-18: «С151АА11» вместо «С151СА99»).
    interval = db.scalars(
        select(BayOccupancy).where(BayOccupancy.exit_event_id == last_exit.id)
    ).first()
    prior_plate = (interval.plate if interval is not None else None) or last_exit.plate
    prior_order_id = _work_order_id_for_plate(db, prior_plate)
    if event.work_order_id is not None and prior_order_id is not None:
        if prior_order_id != event.work_order_id:
            return True
    return not plates_match(event.plate, prior_plate) and _is_confident_read(event)


def _is_noise_while_occupied(open_interval: BayOccupancy, event: BayEvent) -> bool:
    if event.ocr_confidence is not None and float(event.ocr_confidence) < OCCUPIED_NOISE_CONFIDENCE:
        return True
    return plates_match(open_interval.plate, event.plate)


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
    actor_name: str | None = None,
) -> BayEvent:
    if event_type not in EVENT_TYPES:
        raise InvalidEvent(f"Unknown event_type: {event_type}")
    bay = get_bay(db, bay_id)
    image = _decode_image(snapshot_base64)
    if source == "manual":
        # Ручной ввод: время события обязательно и не должно ломать порядок въезд/выезд.
        if occurred_at is None:
            raise InvalidEvent("Укажите время события")
        _check_manual_event_time(db, bay.id, event_type, normalize_plate(plate), occurred_at)
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
        created_by_name=actor_name if source == "manual" else None,
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
            if open_now is None and same_car_interval(db, event) is not None:
                reason = SAME_CAR_NOTE
            elif open_now is None:
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
            _open_interval(db, event, pair_with_exit=source == "manual")
    elif event_type == EVENT_EXIT_CONFIRMED:
        _close_interval(db, event)
    db.commit()
    db.refresh(event)
    return event


def _fmt_local(moment: datetime) -> str:
    return moment.astimezone(SHOP_TZ).strftime("%d.%m %H:%M")


def _orphan_exit_after(
    db: Session, bay_id: uuid.UUID, moment: datetime, plate: str | None
) -> BayEvent | None:
    """Ближайший после `moment` выезд бокса, у которого нет въезда (заезда), если между ними нет
    другого въезда и номера не противоречат друг другу."""
    exits = db.scalars(
        select(BayEvent)
        .where(
            BayEvent.bay_id == bay_id,
            BayEvent.event_type == EVENT_EXIT_CONFIRMED,
            BayEvent.occurred_at > moment,
            ~select(BayOccupancy.id).where(BayOccupancy.exit_event_id == BayEvent.id).exists(),
        )
        .order_by(BayEvent.occurred_at)
    ).all()
    for candidate in exits:
        next_entry = db.scalars(
            select(BayEvent.id).where(
                BayEvent.bay_id == bay_id,
                BayEvent.event_type == EVENT_ENTRY_CONFIRMED,
                BayEvent.occurred_at > moment,
                BayEvent.occurred_at < candidate.occurred_at,
            )
        ).first()
        if next_entry is not None:
            return None  # между ними чужой въезд: этот выезд - не наш
        if plate and candidate.plate and not plates_match(plate, candidate.plate):
            return None
        return candidate
    return None


def _check_manual_event_time(
    db: Session, bay_id: uuid.UUID, event_type: str, plate: str | None, moment: datetime
) -> None:
    """Время ручного события: не в будущем, выезд не раньше въезда, въезд не позже уже
    записанного выезда и не посреди чужого заезда."""
    if moment > datetime.now(UTC):
        raise InvalidEvent("Время события не может быть в будущем")
    if event_type == EVENT_EXIT_CONFIRMED:
        interval = db.scalars(
            select(BayOccupancy)
            .where(BayOccupancy.bay_id == bay_id, BayOccupancy.ended_at.is_(None))
            .order_by(BayOccupancy.started_at.desc())
            .limit(1)
        ).first()
        if interval is not None and moment < interval.started_at:
            raise InvalidEvent(
                f"Выезд не может быть раньше въезда ({_fmt_local(interval.started_at)})"
            )
        return
    if event_type != EVENT_ENTRY_CONFIRMED:
        return
    inside = db.scalars(
        select(BayOccupancy).where(
            BayOccupancy.bay_id == bay_id,
            BayOccupancy.started_at < moment,
            BayOccupancy.ended_at.is_not(None),
            BayOccupancy.ended_at > moment,
        )
    ).first()
    if inside is not None:
        raise InvalidEvent(
            f"В это время бокс был занят: заезд с {_fmt_local(inside.started_at)} "
            f"по {_fmt_local(inside.ended_at)}"
        )
    # Выезд этой же машины уже записан (без въезда), а въезд указан позже него.
    if plate:
        earlier_exit = db.scalars(
            select(BayEvent)
            .where(
                BayEvent.bay_id == bay_id,
                BayEvent.event_type == EVENT_EXIT_CONFIRMED,
                BayEvent.occurred_at <= moment,
                ~select(BayOccupancy.id).where(BayOccupancy.exit_event_id == BayEvent.id).exists(),
            )
            .order_by(BayEvent.occurred_at.desc())
            .limit(1)
        ).first()
        if earlier_exit is not None and plates_match(plate, earlier_exit.plate):
            between = db.scalars(
                select(BayEvent.id).where(
                    BayEvent.bay_id == bay_id,
                    BayEvent.event_type == EVENT_ENTRY_CONFIRMED,
                    BayEvent.occurred_at > earlier_exit.occurred_at,
                    BayEvent.occurred_at <= moment,
                )
            ).first()
            if between is None:
                raise InvalidEvent(
                    "Въезд не может быть позже выезда: выезд этой машины уже записан "
                    f"в {_fmt_local(earlier_exit.occurred_at)}"
                )


def _open_interval(db: Session, event: BayEvent, *, pair_with_exit: bool = False) -> None:
    review = event.review_status
    if pair_with_exit:
        # Ручной въезд за уже записанным выездом (машина «уехала» без въезда): заезд сразу закрыт.
        orphan = _orphan_exit_after(db, event.bay_id, event.occurred_at, event.plate)
        if orphan is not None:
            db.add(
                BayOccupancy(
                    bay_id=event.bay_id,
                    plate=event.plate or orphan.plate,
                    started_at=event.occurred_at,
                    entry_event_id=event.id,
                    ended_at=orphan.occurred_at,
                    exit_event_id=orphan.id,
                    review_status=review,
                )
            )
            return
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
    date_from: date | None = None,
    date_to: date | None = None,
    job_id: uuid.UUID | None = None,
) -> list[dict]:
    """Заезды (интервалы занятости) за дни [date_from, date_to] по времени цеха, свежие первыми.

    День определяется по началу заезда; заезд, который ещё идёт, считается до «сейчас».
    С job_id - заезды, связанные с этой записью планировщика (кнопка «Фото» в записи), за любые дни.
    """
    query = (
        select(BayOccupancy, Bay)
        .join(Bay, Bay.id == BayOccupancy.bay_id)
        .order_by(BayOccupancy.started_at.desc())
        .limit(HISTORY_LIMIT)
    )
    if job_id is not None:
        query = query.where(BayOccupancy.workshop_job_id == job_id)
    else:
        if date_from is None or date_to is None:
            raise ValueError("date_from and date_to are required without job_id")
        start = datetime.combine(date_from, time.min, tzinfo=SHOP_TZ)
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=SHOP_TZ)
        query = query.where(BayOccupancy.started_at >= start, BayOccupancy.started_at < end)
    if bay_id is not None:
        query = query.where(Bay.id == bay_id)
    if workshop_id is not None:
        query = query.where(Bay.workshop_id == workshop_id)
    now = datetime.now(UTC)
    return [history_item(db, interval, bay, now) for interval, bay in db.execute(query).all()]


def history_item(
    db: Session, interval: BayOccupancy, bay: Bay, now: datetime | None = None
) -> dict:
    now = now or datetime.now(UTC)
    entry = db.get(BayEvent, interval.entry_event_id)
    exit_event = db.get(BayEvent, interval.exit_event_id) if interval.exit_event_id else None
    work_order = db.get(WorkOrder, entry.work_order_id) if entry and entry.work_order_id else None
    finished = interval.ended_at or now
    return {
        "id": interval.id,
        "bay_id": bay.id,
        "bay_name": bay.name,
        "plate": interval.plate,
        "no_plate": bool(entry and entry.note and NO_PLATE_NOTE in entry.note),
        "workshop_job_id": interval.workshop_job_id,
        "started_at": interval.started_at,
        "ended_at": interval.ended_at,
        "duration_seconds": max(int((finished - interval.started_at).total_seconds()), 0),
        "review_status": interval.review_status,
        "entry": event_out(entry),
        "exit": event_out(exit_event),
        "work_order_id": work_order.id if work_order else None,
        "work_order_number": work_order.external_number if work_order else None,
    }


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
