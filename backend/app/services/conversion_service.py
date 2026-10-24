"""Телефония -> "Конверсия": inbound calls of a period, grouped by phone and the
work order they (most plausibly) led to.

Matching mirrors leads_service._match_work_order (a lead's work order = the
earliest one on the same phone created after the lead), with one deliberate
difference: "created" here is WorkOrder.created_date (ДатаСоздания, the date
1C created the order - filled for every order), falling back to created_at
only if it's missing. leads_service compares against created_at, which is
when *our* import first saw the row - for the ~300 days of history loaded at
once that is the import day, not the real creation date, so it can't tell
"before the call" from "after the call".

"Существующий" = the phone had at least one work order (any status)
created before the call - warranty work orders (Settings -> Общие) left out
throughout, they never count as a visit, an open order or a conversion.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import NamedTuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.call_record import TOPIC_UNDETERMINED, CallRecord
from app.models.work_order import WorkOrder
from app.models.work_order_status_history import WorkOrderStatusHistory
from app.models.workshop_source_department import WorkshopSourceDepartment
from app.services import (
    settings_service,
    telephony_settings_service,
    telephony_stats_service,
)
from app.services.telephony_stats_service import LineCallEvent

# Russia has used a flat UTC+3 with no DST since 2014 (same constant, same
# reasoning, as in telephony_stats_service/cockpit_service).
_MSK = timezone(timedelta(hours=3))


@dataclass
class ConversionGroup:
    client: str
    work_order_id: uuid.UUID | None
    work_order_number: str | None
    work_order_created_date: datetime | None
    is_existing: bool
    calls: list[LineCallEvent]  # oldest first
    # How the analytics conversion (see classify_phones) treats this group's
    # phone: "new" / "existing_counted" / "existing_excluded", or "none" if
    # it had no real conversation with a defined topic in the period. The
    # "Конверсия" tab filters by it, so a click on a donut shows exactly the
    # numbers that went into it.
    segment: str = "none"
    phone_converted: bool = False  # the phone got a work order (window rule)
    # The phone's class regardless of topic: "new" / "existing_counted" /
    # "existing_excluded" (see classify_phones) - lets the tab show ALL calls
    # of new or existing clients, not just those with a topic conversation.
    client_class: str = "new"
    # Missed and never reached within the period (see PhoneInfo.unanswered).
    phone_unanswered: bool = False
    # This group is its phone's FIRST one that led to a counted work order: the
    # single row per converted number ("Дошли до заказ-наряда").
    conversion_row: bool = False


def _real_moment(stored: datetime | None) -> datetime | None:
    """WorkOrder.created_date / closed_date / end_date / document_date hold
    1C's naive Moscow clock reading stored AS IF IT WERE UTC (the import does
    not convert them, unlike status history, payments and calls, which are
    converted - see import_service._upsert_work_order vs _naive_msk_to_utc),
    so they read 3 hours late. Verified against the status history: a
    work order's closed_date is exactly 3.00 h after its "Закрыт" history
    entry. To compare them with call times, put them back on the real
    instant."""
    if stored is None:
        return None
    return stored.astimezone(UTC).replace(tzinfo=_MSK).astimezone(UTC)


class PhoneWorkOrder(NamedTuple):
    created: datetime  # ДатаСоздания (created_at only if it is missing)
    id: uuid.UUID
    number: str
    status: str | None
    closed_date: datetime | None
    end_date: datetime | None
    document_date: datetime
    department: str | None


def _last10(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else ""


def _work_orders_by_phone(
    db: Session, phones: set[str], skip_repair_types: set[str]
) -> dict[str, list[PhoneWorkOrder]]:
    """Work orders for just the given (normalized) phones, each list sorted
    oldest-created first. WorkOrder.phone is raw 1C passthrough (any
    format), hence normalizing in Python rather than comparing columns.
    Work orders of the given (warranty) repair types are left out."""
    rows = db.execute(
        select(
            WorkOrder.phone,
            WorkOrder.created_date,
            WorkOrder.created_at,
            WorkOrder.id,
            WorkOrder.external_number,
            WorkOrder.status,
            WorkOrder.closed_date,
            WorkOrder.end_date,
            WorkOrder.document_date,
            WorkOrder.department,
            WorkOrder.repair_type,
        ).where(WorkOrder.phone.is_not(None))
    ).all()
    by_phone: dict[str, list[PhoneWorkOrder]] = {}
    for (
        phone,
        created_date,
        created_at,
        work_order_id,
        number,
        status,
        closed_date,
        end_date,
        document_date,
        department,
        repair_type,
    ) in rows:
        normalized = _last10(phone)
        if normalized not in phones or repair_type in skip_repair_types:
            continue
        by_phone.setdefault(normalized, []).append(
            PhoneWorkOrder(
                # created_at (our own insert time) is a real instant already.
                _real_moment(created_date) or created_at,
                work_order_id,
                number,
                status,
                _real_moment(closed_date),
                _real_moment(end_date),
                _real_moment(document_date) or created_at,
                department,
            )
        )
    for entries in by_phone.values():
        entries.sort(key=lambda entry: entry[0])
    return by_phone


def list_conversion(
    db: Session, start_day: date, end_day: date, departments: list[str] | None = None
) -> list[ConversionGroup]:
    """One group per (phone, matched work order): a call is matched to the
    first work order created after it on that phone (calls with none go to
    that phone's "no work order" group), so several calls leading to one
    work order collapse into one row, and a phone with several work orders
    in the period gets one row per work order. `is_existing` is judged at
    the group's first call. Groups are newest-first by that first call."""
    phone_sources = telephony_settings_service.list_phone_sources(db)
    events = telephony_stats_service.list_conversion_calls(db, start_day, end_day, phone_sources)
    workshop_ids = workshop_ids_for_departments(db, departments)
    if workshop_ids is not None:
        events = [e for e in events if e.workshop_id in workshop_ids]
    phones = {e.client for e in events if e.client}
    warranty = set(settings_service.get_app_settings(db).warranty_repair_types or [])
    work_orders = _work_orders_by_phone(db, phones, warranty)

    groups: dict[tuple[str, uuid.UUID | None], ConversionGroup] = {}
    for event in sorted(events, key=lambda e: e.time):
        client = event.client or ""
        call_time = datetime.strptime(event.time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_MSK)
        call_time_utc = call_time.astimezone(UTC)
        candidates = work_orders.get(client, [])
        match: PhoneWorkOrder | None = next((c for c in candidates if c[0] > call_time_utc), None)
        key = (client, match[1] if match else None)
        group = groups.get(key)
        if group is None:
            group = groups[key] = ConversionGroup(
                client=client,
                work_order_id=match[1] if match else None,
                work_order_number=match[2] if match else None,
                work_order_created_date=match[0] if match else None,
                # Judged at the group's first call (events are oldest-first).
                is_existing=any(created < call_time_utc for created, *_ in candidates),
                calls=[],
            )
        group.calls.append(event)

    classification = classify_phones(db, start_day, end_day, departments)
    for group in groups.values():
        info = classification.phones.get(group.client)
        if info is not None:
            group.client_class = info.client_class
            group.segment = info.client_class if info.has_topic else "none"
            group.phone_converted = info.work_orders > 0
            group.phone_unanswered = info.unanswered

    # One conversion row per converted phone: its earliest group whose work
    # order is one of those counted for it.
    best: dict[str, ConversionGroup] = {}
    for group in groups.values():
        info = classification.phones.get(group.client)
        if info is None or group.work_order_id not in info.work_order_ids:
            continue
        current = best.get(group.client)
        if current is None or group.calls[0].time < current.calls[0].time:
            best[group.client] = group
    for group in best.values():
        group.conversion_row = True

    return sorted(groups.values(), key=lambda g: g.calls[0].time, reverse=True)


# ---- Конверсия для страницы Аналитика ---------------------------------------


@dataclass
class ConversionSummary:
    calls_total: int  # every inbound+outbound call of the period
    talk_phones: int  # unique numbers with a real conversation
    topic_phones: int  # ... of those, with a defined topic (not an advert)
    new_clients: int  # ... of those, with no work order before their first call
    converted_new_clients: int  # new clients that got a work order afterwards
    work_orders_new_clients: int  # the work orders they got
    work_orders_total: int  # every work order created in the period
    conversion_pct: float | None  # converted_new_clients / new_clients * 100
    # The same funnel for EXISTING clients - numbers that already had a work
    # order before their first call and whose earlier work orders are all
    # finished (see config.conversion_finished_statuses):
    existing_topic_phones: int  # all existing numbers with a conversation + topic
    existing_excluded: int  # ... dropped: an earlier work order is still open
    existing_clients: int  # ... the rest, i.e. counted
    converted_existing_clients: int
    work_orders_existing_clients: int
    existing_conversion_pct: float | None
    # Figures beside the donuts (all in unique phone numbers): the target ones
    # are new_clients + existing_clients (numbers with a topic conversation,
    # without the existing ones whose repair was in progress that day).
    target_phones: int
    unanswered_new: int  # new numbers missed and never reached in the period
    unanswered_existing: int  # the same for counted-existing numbers


def _has_defined_topic(topic_tag: str | None) -> bool:
    return bool(topic_tag) and topic_tag != TOPIC_UNDETERMINED


def _next_conversation_after(
    db: Session, phones: set[str], after_utc: datetime
) -> dict[str, datetime]:
    """For each phone, when its first real conversation with a defined topic
    (either direction) happened at/after `after_utc` - the end of that
    phone's work-order search window in get_conversion_summary. Phones with
    no later conversation are absent (= no limit)."""
    if not phones:
        return {}
    rows = db.execute(
        select(CallRecord.client, func.min(CallRecord.occurred_at))
        .where(
            CallRecord.client.in_(phones),
            CallRecord.occurred_at >= after_utc,
            CallRecord.talk_sec >= telephony_stats_service.MIN_REAL_TALK_SEC,
            CallRecord.topic_tag.is_not(None),
            CallRecord.topic_tag != TOPIC_UNDETERMINED,
        )
        .group_by(CallRecord.client)
    ).all()
    return {client: first for client, first in rows}


class _StatusResolver:
    """A work order's status AT A GIVEN MOMENT, from 1C's own status history
    (the real ДатаВерсии, down to the minute).

    An order without a usable history (none at all, or one whose last entry
    does not match the order's current status) falls back to what is known:
    a not-finished order is in progress; a finished one finished at
    closed_date, else end_date, else document_date (a refusal has no
    closed_date)."""

    def __init__(
        self,
        timelines: dict[uuid.UUID, list[tuple[datetime, str]]],
        finished_statuses: set[str],
    ) -> None:
        self.timelines = timelines
        self.finished = finished_statuses

    def at(self, wo: PhoneWorkOrder, moment: datetime) -> tuple[datetime | None, str | None]:
        """(when it entered that status, the status) at `moment`; (None, None)
        means it was still in progress (or its status is unknown)."""
        events = self.timelines.get(wo.id)
        if events and events[-1][1] == wo.status:
            current: tuple[datetime, str] | None = None
            for changed_at, status in events:
                if changed_at > moment:
                    break
                current = (changed_at, status)
            return current if current else (None, None)
        if wo.status in self.finished:
            finished_at = wo.closed_date or wo.end_date or wo.document_date
            if finished_at <= moment:
                return finished_at, wo.status
        return None, None


def _status_timelines(
    db: Session, work_order_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[datetime, str]]]:
    timelines: dict[uuid.UUID, list[tuple[datetime, str]]] = {}
    for start in range(0, len(work_order_ids), 1000):
        rows = db.execute(
            select(
                WorkOrderStatusHistory.work_order_id,
                WorkOrderStatusHistory.changed_at,
                WorkOrderStatusHistory.status,
            )
            .where(WorkOrderStatusHistory.work_order_id.in_(work_order_ids[start : start + 1000]))
            .order_by(WorkOrderStatusHistory.work_order_id, WorkOrderStatusHistory.changed_at)
        ).all()
        for work_order_id, changed_at, status in rows:
            timelines.setdefault(work_order_id, []).append((changed_at, status))
    return timelines


def _call_state(
    orders: list[PhoneWorkOrder],
    moment: datetime,
    resolver: _StatusResolver,
    closed_status: str,
) -> str:
    """How a call at `moment` counts, judged against the number's work orders
    at that moment, to the minute (product ask, 2026-10-24):

    - "new": no work order existed yet (any status);
    - "excluded": some work order existing then was NOT finished (a status
      other than Закрыт/Отказ - the client is asking about a repair in
      progress), or was "Закрыт" and moved to that status on the same date
      as the call (the car was being handed over right now);
    - "existing": it had work orders, all finished earlier.

    `orders` must already leave out warranty work orders."""
    call_date = moment.astimezone(_MSK).date()
    existing = False
    for wo in orders:
        if wo.created >= moment:
            continue  # created after the call
        existing = True
        since, status = resolver.at(wo, moment)
        if status is None or status not in resolver.finished:
            return "excluded"
        if (
            status == closed_status
            and since is not None
            and since.astimezone(_MSK).date() == call_date
        ):
            return "excluded"
    return "existing" if existing else "new"


@dataclass
class PhoneInfo:
    client_class: str  # "new" | "existing_counted" | "existing_excluded"
    calls: int  # every call (in/out) of the period
    topic_calls: int  # ... that were a real conversation with a defined topic
    # At least one such conversation that was NOT excluded (see _call_state):
    # the number is part of the target calls and of the conversion.
    has_topic: bool
    # It had such conversations, but every one of them was excluded.
    had_qualifying: bool
    work_orders: int  # work orders it got after its counted call (window rule)
    work_order_ids: list[uuid.UUID]  # ... which ones
    # It had a missed inbound call and no real conversation (either direction)
    # after the last one before the period ended - "остались без ответа".
    unanswered: bool = False


@dataclass
class Classification:
    calls_total: int
    talk_phones: int  # unique numbers with a real conversation
    phones: dict[str, PhoneInfo]  # EVERY number that called in the period
    period_start_utc: datetime
    period_end_utc: datetime


def workshop_ids_for_departments(
    db: Session, departments: list[str] | None
) -> set[uuid.UUID] | None:
    """The workshops that Settings maps to the given raw 1C departments (what
    the dashboard's department filter selects) - None when no department is
    selected (= everything). Calls are attributed to a workshop by the phone
    line / extension tables (see call_workshop_service), which are keyed by
    those same workshops."""
    if not departments:
        return None
    return set(
        db.scalars(
            select(WorkshopSourceDepartment.workshop_id).where(
                WorkshopSourceDepartment.source_department.in_(departments)
            )
        )
    )


def classify_phones(
    db: Session, start_day: date, end_day: date, departments: list[str] | None = None
) -> Classification:
    """Sort the period's phone numbers into client classes and work out the
    conversion (product ask, 2026-10-24) - one entry per unique number.

    A CALL counts as "a conversation with a topic" if it was answered for
    >= MIN_REAL_TALK_SEC AND has a defined topic (no topic = an advert/robot);
    outbound calls count only as a callback to a missed inbound
    (CALLBACK_WINDOW).

    Each such call is judged on its own, to the minute, against the number's
    work orders at that moment (see _call_state): "new" (none yet),
    "existing" (some, all finished earlier) or "excluded" (an unfinished
    one, or one closed that very day - a call about a repair in progress).
    Excluded calls stay out of the pool. A number is in the target calls and
    the conversion once, through its first non-excluded call, as "new" or
    "existing_counted"; a number whose every such call was excluded is
    "existing_excluded". Warranty work orders (Settings -> Общие) are ignored
    everywhere here: they neither make a client existing, nor count as an open
    order, nor as a conversion.

    A number is "converted" (work_orders > 0) if a non-warranty work order was
    created for it after its counted call and before its NEXT real
    conversation (with a defined topic) after the period - or with no limit
    if there is none. Nothing is cut at the period's end (a call on 30.09
    followed by a work order on 01.10 is September's conversion).

    `departments` (raw 1C department names, the dashboard's filter) narrows
    it to one workshop: only calls attributed to the workshops mapped to
    those departments are counted, and only work orders of those departments
    count as conversions. Whether a number is new / existing / excluded is
    always judged company-wide - a repair in progress in another workshop is
    still a repair in progress."""
    workshop_ids = workshop_ids_for_departments(db, departments)
    head, period, _tail = telephony_stats_service.fetch_conversion_window(db, start_day, end_day)
    by_client: dict[str, list[telephony_stats_service._Rec]] = {}
    for rec in head + period:
        if rec.client:
            by_client.setdefault(rec.client, []).append(rec)
    if workshop_ids is not None:
        period = [r for r in period if r.workshop_id in workshop_ids]

    def to_utc(naive_msk: datetime) -> datetime:
        return naive_msk.replace(tzinfo=_MSK).astimezone(UTC)

    calls_total = 0
    calls_by_phone: dict[str, int] = {}
    first_call: dict[str, datetime] = {}
    last_miss: dict[str, datetime] = {}
    last_contact: dict[str, datetime] = {}
    talk_phones: set[str] = set()
    qualifying: dict[str, list[telephony_stats_service._Rec]] = {}
    for rec in sorted(period, key=lambda r: r.time):
        if rec.type not in ("IN", "OUT"):
            continue
        calls_total += 1
        if not rec.client:
            continue
        calls_by_phone[rec.client] = calls_by_phone.get(rec.client, 0) + 1
        first_call.setdefault(rec.client, rec.time)
        is_conversation = rec.talk >= telephony_stats_service.MIN_REAL_TALK_SEC
        if rec.type == "IN" and not rec.answered:
            last_miss[rec.client] = rec.time
        if is_conversation:
            last_contact[rec.client] = rec.time
        counts = rec.type == "IN" or telephony_stats_service.has_earlier_miss(rec, by_client)
        if is_conversation and counts:
            talk_phones.add(rec.client)
            if _has_defined_topic(rec.topic_tag):
                qualifying.setdefault(rec.client, []).append(rec)

    period_start_utc = to_utc(datetime.combine(start_day, datetime.min.time()))
    period_end_utc = to_utc(datetime.combine(end_day + timedelta(days=1), datetime.min.time()))

    settings = get_settings()
    finished_statuses = set(settings.conversion_finished_statuses_list)
    warranty = set(settings_service.get_app_settings(db).warranty_repair_types or [])
    all_phones = set(first_call)
    work_orders = _work_orders_by_phone(db, all_phones, warranty)
    resolver = _StatusResolver(
        _status_timelines(
            db,
            [
                wo.id
                for phone in all_phones
                for wo in work_orders.get(phone, [])
                if wo.created < period_end_utc
            ],
        ),
        finished_statuses,
    )

    def state_at(phone: str, rec_time: datetime) -> str:
        return _call_state(
            work_orders.get(phone, []),
            to_utc(rec_time),
            resolver,
            settings.conversion_closed_status,
        )

    # 1. each number's counted call = its first qualifying call that is not excluded
    counted_call: dict[str, tuple[datetime, str]] = {}
    for phone, recs in qualifying.items():
        for rec in recs:
            state = state_at(phone, rec.time)
            if state != "excluded":
                counted_call[phone] = (rec.time, state)
                break

    next_conversation = _next_conversation_after(db, set(counted_call), period_end_utc)

    phones: dict[str, PhoneInfo] = {}
    for phone in all_phones:
        unanswered = phone in last_miss and (
            phone not in last_contact or last_contact[phone] < last_miss[phone]
        )
        if phone in counted_call:
            counted_time, state = counted_call[phone]
        else:
            # Not a target number. Class it by the call that matters most:
            # its first (excluded) qualifying call, else the last missed one
            # if nobody got back to it, else its first call.
            if qualifying.get(phone):
                ref = qualifying[phone][0].time
            else:
                ref = last_miss[phone] if unanswered else first_call[phone]
            state = state_at(phone, ref)
        client_class = {
            "new": "new",
            "existing": "existing_counted",
            "excluded": "existing_excluded",
        }[state]

        led_to: list[uuid.UUID] = []
        if phone in counted_call:
            counted_utc = to_utc(counted_time)
            window_end = next_conversation.get(phone)
            led_to = [
                wo.id
                for wo in work_orders.get(phone, [])
                if counted_utc < wo.created
                and (window_end is None or wo.created < window_end)
                and (departments is None or wo.department in departments)
            ]
        phones[phone] = PhoneInfo(
            client_class=client_class,
            calls=calls_by_phone[phone],
            topic_calls=len(qualifying.get(phone, [])),
            has_topic=phone in counted_call,
            had_qualifying=phone in qualifying,
            work_orders=len(led_to),
            work_order_ids=led_to,
            unanswered=unanswered,
        )

    return Classification(
        calls_total=calls_total,
        talk_phones=len(talk_phones),
        phones=phones,
        period_start_utc=period_start_utc,
        period_end_utc=period_end_utc,
    )


def get_conversion_summary(
    db: Session, start_day: date, end_day: date, departments: list[str] | None = None
) -> ConversionSummary:
    """The numbers behind the two conversion donuts on Аналитика - see
    classify_phones for the rules. conversion_pct = new numbers that got a
    work order / new numbers; existing_conversion_pct = counted existing
    numbers that got one / counted existing numbers (both over the numbers
    in the target calls, each number once - a client with two work orders
    is still one converted client; the work orders themselves are shown
    beside the donut). The figures beside the donuts are
    unique numbers too: see ConversionSummary."""
    classification = classify_phones(db, start_day, end_day, departments)
    infos = list(classification.phones.values())

    new_all = [x for x in infos if x.client_class == "new"]
    counted_all = [x for x in infos if x.client_class == "existing_counted"]
    excluded_topic = [x for x in infos if x.had_qualifying and not x.has_topic]
    new = [x for x in new_all if x.has_topic]
    counted = [x for x in counted_all if x.has_topic]
    new_converted = [x for x in new if x.work_orders]
    counted_converted = [x for x in counted if x.work_orders]

    # created_date is stored on the "Moscow clock read as UTC" scale (see
    # _real_moment), so the period's bounds are midnights on that same scale.
    total_filters = [
        WorkOrder.created_date >= datetime.combine(start_day, datetime.min.time(), tzinfo=UTC),
        WorkOrder.created_date
        < datetime.combine(end_day + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
    ]
    if settings_service.get_app_settings(db).exclude_internal_orders:
        total_filters.append(WorkOrder.is_internal.is_(False))
    warranty = settings_service.get_app_settings(db).warranty_repair_types
    if warranty:
        total_filters.append(
            or_(WorkOrder.repair_type.is_(None), WorkOrder.repair_type.not_in(warranty))
        )
    if departments:
        total_filters.append(WorkOrder.department.in_(departments))
    work_orders_total = db.scalar(select(func.count()).select_from(WorkOrder).where(*total_filters))

    return ConversionSummary(
        calls_total=classification.calls_total,
        talk_phones=classification.talk_phones,
        topic_phones=sum(1 for x in infos if x.has_topic),
        new_clients=len(new),
        converted_new_clients=len(new_converted),
        work_orders_new_clients=sum(x.work_orders for x in new_converted),
        work_orders_total=work_orders_total or 0,
        conversion_pct=round(len(new_converted) / len(new) * 100, 1) if new else None,
        existing_topic_phones=len(counted) + len(excluded_topic),
        existing_excluded=len(excluded_topic),
        existing_clients=len(counted),
        converted_existing_clients=len(counted_converted),
        work_orders_existing_clients=sum(x.work_orders for x in counted_converted),
        existing_conversion_pct=(
            round(len(counted_converted) / len(counted) * 100, 1) if counted else None
        ),
        target_phones=len(new) + len(counted),
        unanswered_new=sum(1 for x in new_all if x.unanswered),
        unanswered_existing=sum(1 for x in counted_all if x.unanswered),
    )


def conversion_work_order_ids(
    db: Session,
    start_day: date,
    end_day: date,
    kind: str,
    departments: list[str] | None = None,
) -> list[uuid.UUID]:
    """The work orders counted in "Заказ-нарядов" beside a donut - those of
    the new ("new") or counted existing ("existing") clients of
    classify_phones. The work-order list opens on exactly these."""
    wanted = "new" if kind == "new" else "existing_counted"
    classification = classify_phones(db, start_day, end_day, departments)
    return [
        work_order_id
        for info in classification.phones.values()
        if info.has_topic and info.client_class == wanted
        for work_order_id in info.work_order_ids
    ]
