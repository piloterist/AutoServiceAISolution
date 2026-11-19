"""Ворота кузовного цеха: машина проезжает под камерой, не останавливаясь (въезд), и так же
выезжает; внутри их сколько угодно. Бокс здесь не нужен: «в цехе» = заезд (GateStay) без выезда.

Правила (product ask, 2026-11-19):
- заезд ищет свою запись в кузовном планировщике (BodyCar) по номеру/заказ-наряду; не нашли -
  ничего не создаём, а пишем ошибку «нет в плане» (кузов планирует все машины, заездов «с колёс»
  нет); нашли - карточке ставится «На территории»;
- выезд ищет свою машину среди тех, что сейчас в цехе (номер читается неточно - сравниваем с
  коротким списком присутствующих, это надёжнее, чем читать номер с нуля); не нашли - ошибка
  «выезд без въезда»;
- одна машина может выезжать и возвращаться: каждый проезд - отдельный заезд, все они
  привязаны к одной карточке плана;
- номер не распознан или машины без номера - заезд и выезд вводятся руками.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.bay import (
    BAY_KIND_GATE,
    EVENT_ENTRY_CONFIRMED,
    EVENT_EXIT_CONFIRMED,
    ISSUE_EXIT_WITHOUT_ENTRY,
    ISSUE_NO_BODY_PLAN,
    ISSUE_RESOLVED_AUTO,
    REVIEW_AUTO,
    REVIEW_CONFIRMED,
    REVIEW_NEEDS,
    SOURCE_MANUAL,
    Bay,
    BayEvent,
    BayIssue,
    GateStay,
)
from app.models.body_car import BodyCar
from app.models.planner_constants import CAR_STATUS_DONE
from app.models.work_order import WorkOrder
from app.services import audit_log_service
from app.services.bay_service import (
    SHOP_TZ,
    BayNotFound,
    InvalidEvent,
    _decode_image,
    _event_path,
    _upload,
    _work_order_id_for_plate,
    event_out,
    get_bay,
    normalize_plate,
    plate_from_description,
    plates_match,
)
from app.services.planner_service import ENTITY_BODY_CAR

logger = structlog.get_logger(__name__)

ACTOR_NAME = "Видеоконтроль"
# Повторный въезд той же машины за такой срок - то же чтение номера (след распался на два), а не
# новый заезд.
DUPLICATE_WINDOW = timedelta(minutes=2)
DUPLICATE_NOTE = "повторное чтение въезда той же машины: не учтён"
MISSED_EXIT_NOTE = "выезд не зафиксирован: заезд закрыт новым въездом той же машины"


class StayNotFound(Exception):
    pass


# ---- сопоставление ----------------------------------------------------------


def _car_plate(db: Session, car: BodyCar) -> str | None:
    """Номер карточки плана: введённый, иначе из описания машины, иначе из её заказ-наряда."""
    plate = normalize_plate(car.plate) or plate_from_description(car.car_description)
    if plate or car.work_order_id is None:
        return normalize_plate(plate)
    order = db.get(WorkOrder, car.work_order_id)
    return normalize_plate(plate_from_description(order.vehicle_description)) if order else None


def find_body_car(
    db: Session, workshop_id: uuid.UUID, plate: str | None, work_order_id: uuid.UUID | None
) -> BodyCar | None:
    """Карточка кузовного плана этой машины: по заказ-наряду, затем по номеру (допускаем одну
    ошибку чтения). Выданные машины не берём. Из нескольких подходящих - самая свежая."""
    cars = db.scalars(
        select(BodyCar).where(BodyCar.workshop_id == workshop_id, BodyCar.status != CAR_STATUS_DONE)
    ).all()
    best: tuple[int, datetime, BodyCar] | None = None
    for car in cars:
        score = 0
        if work_order_id is not None and car.work_order_id == work_order_id:
            score = 3
        elif plate:
            car_plate = _car_plate(db, car)
            if car_plate and car_plate[:6] == plate[:6]:
                score = 3
            elif plates_match(car_plate, plate):
                score = 2
        if score and (best is None or (score, car.created_at) > (best[0], best[1])):
            best = (score, car.created_at, car)
    return best[2] if best else None


def _same_car_score(stay: GateStay, plate: str | None, work_order_id: uuid.UUID | None) -> int:
    if work_order_id is not None and stay.work_order_id == work_order_id:
        return 3
    if stay.plate and plate and stay.plate[:6] == plate[:6]:
        return 3
    if plates_match(stay.plate, plate):
        return 2
    return 0


def _open_stays(db: Session, bay_id: uuid.UUID | None = None) -> list[GateStay]:
    query = select(GateStay).where(GateStay.exited_at.is_(None))
    if bay_id is not None:
        query = query.where(GateStay.bay_id == bay_id)
    return list(db.scalars(query.order_by(GateStay.entered_at)))


# ---- «На территории» --------------------------------------------------------


def _set_on_site(db: Session, car: BodyCar, value: bool) -> None:
    if car.on_site == value:
        return
    car.on_site = value
    audit_log_service.record_change(
        db,
        entity_type=ENTITY_BODY_CAR,
        entity_id=car.id,
        action="update",
        changes={"on_site": {"old": not value, "new": value}},
        actor_user_id=None,
        actor_name=ACTOR_NAME,
        work_order_id=car.work_order_id,
        car_description=car.car_description,
    )


def _refresh_on_site(db: Session, car_id: uuid.UUID | None) -> None:
    """Карточка «на территории», пока есть хоть один её заезд без выезда."""
    if car_id is None:
        return
    car = db.get(BodyCar, car_id)
    if car is None:
        return
    db.flush()  # счётчик ниже - запрос: сначала сбрасываем выезд/привязку этой операции
    inside = db.scalar(
        select(func.count())
        .select_from(GateStay)
        .where(GateStay.body_car_id == car_id, GateStay.exited_at.is_(None))
    )
    _set_on_site(db, car, bool(inside))


# ---- ошибки -----------------------------------------------------------------


def _open_issue(
    db: Session, bay: Bay, kind: str, event: BayEvent, plate: str | None, message: str
) -> None:
    db.add(
        BayIssue(
            bay_id=bay.id,
            entry_event_id=event.id,
            kind=kind,
            plate=plate,
            message=message,
            occurred_at=event.occurred_at,
        )
    )
    logger.warning("gate_issue", kind=kind, plate=plate, bay=bay.name)


def _resolve_issues(db: Session, entry_event_id: uuid.UUID | None, kind: str, note: str) -> None:
    if entry_event_id is None:
        return
    for issue in db.scalars(
        select(BayIssue).where(
            BayIssue.entry_event_id == entry_event_id,
            BayIssue.kind == kind,
            BayIssue.resolved_at.is_(None),
        )
    ):
        issue.resolved_at = datetime.now(UTC)
        issue.resolution = ISSUE_RESOLVED_AUTO
        issue.resolved_by = ACTOR_NAME
        issue.resolution_note = note


def _no_plan_message(plate: str | None, label: str | None = None) -> str:
    who = f"Машина {plate}" if plate else f"Машина ({label or 'номер не распознан'})"
    return f"{who} въехала в кузовной цех, а её нет в плане кузовного."


# ---- события ворот ----------------------------------------------------------


def _make_event(
    db: Session,
    bay: Bay,
    *,
    event_type: str,
    plate: str | None,
    ocr_confidence,
    occurred_at: datetime,
    note: str | None,
    snapshot_base64: str | None,
    source: str,
    needs_review: bool,
) -> BayEvent:
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
            REVIEW_CONFIRMED
            if source == SOURCE_MANUAL
            else REVIEW_NEEDS
            if needs_review
            else REVIEW_AUTO
        ),
    )
    if event_type == EVENT_ENTRY_CONFIRMED:
        event.work_order_id = _work_order_id_for_plate(db, event.plate)
    image = _decode_image(snapshot_base64)
    if image is not None:
        path = _event_path(bay.id, event.id)
        if _upload(db, bay.id, path, image, overwrite=False):
            event.snapshot_path = path
    db.add(event)
    db.flush()
    return event


def _append_note(event: BayEvent, text: str) -> None:
    event.note = f"{event.note}; {text}" if event.note else text


def _on_entry(
    db: Session, bay: Bay, event: BayEvent, *, label: str | None = None, count_always: bool = False
) -> GateStay | None:
    plate = event.plate
    order_id = event.work_order_id
    open_stays = _open_stays(db, bay.id)
    same = [s for s in open_stays if _same_car_score(s, plate, order_id)]
    if same and not count_always:
        newest = max(same, key=lambda s: s.entered_at)
        if event.occurred_at - newest.entered_at <= DUPLICATE_WINDOW:
            _append_note(event, DUPLICATE_NOTE)
            return None
    for stale in same:  # та же машина уже «в цехе»: её выезд не увидели
        stale.exited_at = event.occurred_at
        stale.review_status = REVIEW_NEEDS
        stale.note = f"{stale.note}; {MISSED_EXIT_NOTE}" if stale.note else MISSED_EXIT_NOTE

    car = find_body_car(db, bay.workshop_id, plate, order_id)
    stay = GateStay(
        bay_id=bay.id,
        plate=plate,
        label=label,
        entered_at=event.occurred_at,
        entry_event_id=event.id,
        body_car_id=car.id if car else None,
        work_order_id=order_id or (car.work_order_id if car else None),
        review_status=REVIEW_NEEDS
        if event.review_status == REVIEW_NEEDS or not plate
        else REVIEW_AUTO,
        source=event.source,
        note=event.note,
    )
    if event.source == SOURCE_MANUAL:
        stay.review_status = REVIEW_CONFIRMED
    db.add(stay)
    db.flush()
    for stale in same:
        _refresh_on_site(
            db, stale.body_car_id
        )  # после создания нового заезда: без лишнего «снял-поставил»
    if car is not None:
        _set_on_site(db, car, True)
    else:
        _open_issue(db, bay, ISSUE_NO_BODY_PLAN, event, plate, _no_plan_message(plate, label))
    return stay


def _on_exit(db: Session, bay: Bay, event: BayEvent) -> GateStay | None:
    plate = event.plate
    scored = [(s, _same_car_score(s, plate, None)) for s in _open_stays(db, bay.id)]
    scored = [(s, score) for s, score in scored if score]
    if not scored:
        who = f"Машина {plate}" if plate else "Машина (номер не распознан)"
        _open_issue(
            db,
            bay,
            ISSUE_EXIT_WITHOUT_ENTRY,
            event,
            plate,
            f"{who} выехала из кузовного цеха, а въезда в цех нет (его не увидела камера или "
            "машина уже отмечена выехавшей).",
        )
        return None
    top = max(score for _, score in scored)
    candidates = [s for s, score in scored if score == top]
    stay = candidates[0]  # из нескольких похожих - та, что дольше всех в цехе
    stay.exited_at = event.occurred_at
    stay.exit_event_id = event.id
    if len(candidates) > 1 or event.review_status == REVIEW_NEEDS:
        stay.review_status = REVIEW_NEEDS
    _refresh_on_site(db, stay.body_car_id)
    return stay


def record_pass(
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
    """Событие с камеры на воротах (или ручное): въезд или выезд."""
    bay = get_bay(db, bay_id)
    if bay.kind != BAY_KIND_GATE:
        raise InvalidEvent("not a gate")
    if event_type not in (EVENT_ENTRY_CONFIRMED, EVENT_EXIT_CONFIRMED):
        raise InvalidEvent(f"Unsupported event_type for a gate: {event_type}")
    event = _make_event(
        db,
        bay,
        event_type=event_type,
        plate=plate,
        ocr_confidence=ocr_confidence,
        occurred_at=occurred_at or datetime.now(UTC),
        note=note,
        snapshot_base64=snapshot_base64,
        source=source,
        needs_review=needs_review,
    )
    if event_type == EVENT_ENTRY_CONFIRMED:
        _on_entry(db, bay, event, count_always=source == SOURCE_MANUAL)
    else:
        _on_exit(db, bay, event)
    db.commit()
    db.refresh(event)
    return event


# ---- ручные действия --------------------------------------------------------


def get_stay(db: Session, stay_id: uuid.UUID) -> GateStay:
    stay = db.get(GateStay, stay_id)
    if stay is None:
        raise StayNotFound(str(stay_id))
    return stay


def create_manual_stay(
    db: Session,
    bay_id: uuid.UUID,
    *,
    plate: str | None,
    label: str | None,
    entered_at: datetime | None,
) -> GateStay:
    """Въезд, введённый руками: машина без номера или заезд, которого камера не увидела."""
    plate = normalize_plate(plate)
    label = (label or "").strip() or None
    if not plate and not label:
        raise InvalidEvent("Укажите номер или описание машины")
    bay = get_bay(db, bay_id)
    if bay.kind != BAY_KIND_GATE:
        raise InvalidEvent("not a gate")
    event = _make_event(
        db,
        bay,
        event_type=EVENT_ENTRY_CONFIRMED,
        plate=plate,
        ocr_confidence=None,
        occurred_at=entered_at or datetime.now(UTC),
        note="введён вручную",
        snapshot_base64=None,
        source=SOURCE_MANUAL,
        needs_review=False,
    )
    stay = _on_entry(db, bay, event, label=label, count_always=True)
    db.commit()
    assert stay is not None
    db.refresh(stay)
    return stay


def exit_stay(db: Session, stay_id: uuid.UUID, *, exited_at: datetime | None) -> GateStay:
    """Выезд, отмеченный руками (камера не увидела или у машины нет номера)."""
    stay = get_stay(db, stay_id)
    if stay.exited_at is not None:
        raise InvalidEvent("Машина уже отмечена выехавшей")
    bay = get_bay(db, stay.bay_id)
    event = _make_event(
        db,
        bay,
        event_type=EVENT_EXIT_CONFIRMED,
        plate=stay.plate,
        ocr_confidence=None,
        occurred_at=exited_at or datetime.now(UTC),
        note="введён вручную",
        snapshot_base64=None,
        source=SOURCE_MANUAL,
        needs_review=False,
    )
    stay.exited_at = event.occurred_at
    stay.exit_event_id = event.id
    stay.review_status = REVIEW_CONFIRMED
    _refresh_on_site(db, stay.body_car_id)
    db.commit()
    db.refresh(stay)
    return stay


def update_stay(
    db: Session, stay_id: uuid.UUID, *, plate: str | None, label: str | None
) -> GateStay:
    """Поправить номер/описание (камера прочитала не так): запись плана ищется заново."""
    stay = get_stay(db, stay_id)
    bay = get_bay(db, stay.bay_id)
    stay.plate = normalize_plate(plate)
    stay.label = (label or "").strip() or None
    if not stay.plate and not stay.label:
        raise InvalidEvent("Укажите номер или описание машины")
    stay.review_status = REVIEW_CONFIRMED
    old_car = stay.body_car_id
    order_id = _work_order_id_for_plate(db, stay.plate)
    car = find_body_car(db, bay.workshop_id, stay.plate, order_id)
    stay.body_car_id = car.id if car else None
    stay.work_order_id = order_id or (car.work_order_id if car else None)
    if car is not None:
        _resolve_issues(db, stay.entry_event_id, ISSUE_NO_BODY_PLAN, "Номер исправлен, план найден")
    _refresh_on_site(db, old_car)
    _refresh_on_site(db, stay.body_car_id)
    db.commit()
    db.refresh(stay)
    return stay


def reconcile(db: Session) -> int:
    """Раз в минуту: для машин в цеху, чьей записи в плане не было, ищем её снова (план мог
    появиться позже); нашли - привязываем, «На территории» и ошибка «нет в плане» снимается."""
    linked = 0
    for stay in _open_stays(db):
        if stay.body_car_id is not None:
            continue
        bay = db.get(Bay, stay.bay_id)
        if bay is None:
            continue
        order_id = stay.work_order_id or _work_order_id_for_plate(db, stay.plate)
        car = find_body_car(db, bay.workshop_id, stay.plate, order_id)
        if car is None:
            continue
        stay.body_car_id = car.id
        stay.work_order_id = stay.work_order_id or car.work_order_id
        _set_on_site(db, car, True)
        _resolve_issues(db, stay.entry_event_id, ISSUE_NO_BODY_PLAN, "Машина появилась в плане")
        linked += 1
    return linked


# ---- списки -----------------------------------------------------------------


def inside_count(db: Session, bay_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(GateStay)
            .where(GateStay.bay_id == bay_id, GateStay.exited_at.is_(None))
        )
        or 0
    )


def stay_out(db: Session, stay: GateStay, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    bay = db.get(Bay, stay.bay_id)
    car = db.get(BodyCar, stay.body_car_id) if stay.body_car_id else None
    order = db.get(WorkOrder, stay.work_order_id) if stay.work_order_id else None
    if order is None and car is not None and car.work_order_id is not None:
        order = db.get(WorkOrder, car.work_order_id)
    finished = stay.exited_at or now
    return {
        "id": stay.id,
        "bay_id": stay.bay_id,
        "bay_name": bay.name if bay else "",
        "plate": stay.plate,
        "label": stay.label,
        "entered_at": stay.entered_at,
        "exited_at": stay.exited_at,
        "duration_seconds": max(int((finished - stay.entered_at).total_seconds()), 0),
        "review_status": stay.review_status,
        "source": stay.source,
        "note": stay.note,
        "entry": event_out(db.get(BayEvent, stay.entry_event_id) if stay.entry_event_id else None),
        "exit": event_out(db.get(BayEvent, stay.exit_event_id) if stay.exit_event_id else None),
        "body_car_id": car.id if car else None,
        "car_description": (car.car_description if car else None)
        or (order.vehicle_description if order else None),
        "client_name": (car.client_name if car else None)
        or (order.customer_name if order else None),
        "car_status": car.status if car else None,
        "work_order_id": order.id if order else None,
        "work_order_number": order.external_number if order else None,
        "has_plan": car is not None,
    }


def list_stays(
    db: Session,
    *,
    workshop_id: uuid.UUID | None = None,
    inside_only: bool = True,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    query = select(GateStay).join(Bay, Bay.id == GateStay.bay_id).where(Bay.kind == BAY_KIND_GATE)
    if workshop_id is not None:
        query = query.where(Bay.workshop_id == workshop_id)
    if inside_only:
        query = query.where(GateStay.exited_at.is_(None))
    else:
        if date_to is not None:
            end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=SHOP_TZ)
            query = query.where(GateStay.entered_at < end)
        if date_from is not None:
            start = datetime.combine(date_from, time.min, tzinfo=SHOP_TZ)
            query = query.where((GateStay.exited_at.is_(None)) | (GateStay.exited_at >= start))
    stays = db.scalars(query.order_by(GateStay.entered_at.desc()).limit(1000)).all()
    now = datetime.now(UTC)
    return [stay_out(db, stay, now) for stay in stays]


__all__ = [
    "BayNotFound",
    "InvalidEvent",
    "StayNotFound",
    "create_manual_stay",
    "exit_stay",
    "find_body_car",
    "inside_count",
    "list_stays",
    "reconcile",
    "record_pass",
    "update_stay",
]
