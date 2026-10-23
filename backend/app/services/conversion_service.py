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
created before the call.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.work_order import WorkOrder
from app.services import telephony_settings_service, telephony_stats_service
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


def _last10(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else ""


def _work_orders_by_phone(
    db: Session, phones: set[str]
) -> dict[str, list[tuple[datetime, uuid.UUID, str]]]:
    """Work orders for just the given (normalized) phones, each list sorted
    oldest-created first. WorkOrder.phone is raw 1C passthrough (any
    format), hence normalizing in Python rather than comparing columns."""
    rows = db.execute(
        select(
            WorkOrder.phone,
            WorkOrder.created_date,
            WorkOrder.created_at,
            WorkOrder.id,
            WorkOrder.external_number,
        ).where(WorkOrder.phone.is_not(None))
    ).all()
    by_phone: dict[str, list[tuple[datetime, uuid.UUID, str]]] = {}
    for phone, created_date, created_at, work_order_id, number in rows:
        normalized = _last10(phone)
        if normalized not in phones:
            continue
        by_phone.setdefault(normalized, []).append(
            (created_date or created_at, work_order_id, number)
        )
    for entries in by_phone.values():
        entries.sort(key=lambda entry: entry[0])
    return by_phone


def list_conversion(db: Session, start_day: date, end_day: date) -> list[ConversionGroup]:
    """One group per (phone, matched work order): a call is matched to the
    first work order created after it on that phone (calls with none go to
    that phone's "no work order" group), so several calls leading to one
    work order collapse into one row, and a phone with several work orders
    in the period gets one row per work order. `is_existing` is judged at
    the group's first call. Groups are newest-first by that first call."""
    phone_sources = telephony_settings_service.list_phone_sources(db)
    events = telephony_stats_service.list_conversion_calls(db, start_day, end_day, phone_sources)
    phones = {e.client for e in events if e.client}
    work_orders = _work_orders_by_phone(db, phones)

    groups: dict[tuple[str, uuid.UUID | None], ConversionGroup] = {}
    for event in sorted(events, key=lambda e: e.time):
        client = event.client or ""
        call_time = datetime.strptime(event.time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_MSK)
        call_time_utc = call_time.astimezone(UTC)
        candidates = work_orders.get(client, [])
        match: tuple[datetime, uuid.UUID, str] | None = next(
            (c for c in candidates if c[0] > call_time_utc), None
        )
        key = (client, match[1] if match else None)
        group = groups.get(key)
        if group is None:
            group = groups[key] = ConversionGroup(
                client=client,
                work_order_id=match[1] if match else None,
                work_order_number=match[2] if match else None,
                work_order_created_date=match[0] if match else None,
                # Judged at the group's first call (events are oldest-first).
                is_existing=any(created < call_time_utc for created, _, _ in candidates),
                calls=[],
            )
        group.calls.append(event)

    return sorted(groups.values(), key=lambda g: g.calls[0].time, reverse=True)
