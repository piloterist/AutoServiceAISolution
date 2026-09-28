"""Fetch calls from the configured provider (Zeon today - see
models/telephony_settings.py's PROVIDER_ZEON) and upsert them into
telephony_calls.

See services/zeon_client.py for the provider-specific fetch/normalize step
and models/call_record.py's docstring for why this is a plain bulk upsert
keyed on (provider, external_id), with no separate import-batch bookkeeping
like the 1C import's ImportBatch (see services/import_service.py) - a call
either matches a row that's already there or it doesn't, there's nothing
here that needs auditing across repeated deliveries the way a whole 1C
export payload does.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.call_record import CallRecord
from app.models.telephony_settings import PROVIDER_ZEON, TelephonySettings
from app.services import zeon_client
from app.services.zeon_client import NormalizedCall, ZeonError, ZeonSettings


class TelephonyImportError(Exception):
    """Raised when the configured provider can't be reached, or telephony
    isn't configured yet."""


# Same fixed-offset duplication as zeon_client._MSK/telephony_stats_service._MSK
# - Russia has used a flat UTC+3 with no DST since 2014.
_MSK = timezone(timedelta(hours=3))


@dataclass
class TelephonyImportResult:
    fetched: int
    upserted: int


def zeon_settings_from(settings: TelephonySettings) -> ZeonSettings:
    if not settings.zeon_api_url or not settings.zeon_api_key:
        raise TelephonyImportError("Zeon API URL/key not configured - see Settings -> IP-телефония")
    return ZeonSettings(
        api_url=settings.zeon_api_url, api_key=settings.zeon_api_key, auth=settings.zeon_auth
    )


def _upsert_calls(db: Session, provider: str, calls: list[NormalizedCall]) -> int:
    if not calls:
        return 0
    rows = [
        {
            "id": uuid.uuid4(),
            "provider": provider,
            "external_id": call.external_id,
            "linkedid": call.linkedid,
            "call_date": date.fromisoformat(call.call_date_iso),
            "occurred_at": call.occurred_at,
            "call_type": call.call_type,
            "client": call.client,
            "line": call.line,
            "operator": call.operator,
            "rang_not_answered": call.rang_not_answered or None,
            "wait_sec": call.wait_sec,
            "talk_sec": call.talk_sec,
            "answered": call.answered,
            "raw_payload": call.raw,
        }
        for call in calls
    ]

    # Core table, not the ORM class - same reasoning as
    # import_service._upsert_work_order: ORM onupdate=func.now() never
    # fires on a raw ON CONFLICT DO UPDATE, so updated_at is set explicitly
    # in `set_` below instead.
    table = CallRecord.__table__
    stmt = pg_insert(table).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.c.provider, table.c.external_id],
        set_={
            "linkedid": stmt.excluded.linkedid,
            "call_date": stmt.excluded.call_date,
            "occurred_at": stmt.excluded.occurred_at,
            "call_type": stmt.excluded.call_type,
            "client": stmt.excluded.client,
            "line": stmt.excluded.line,
            "operator": stmt.excluded.operator,
            "rang_not_answered": stmt.excluded.rang_not_answered,
            "wait_sec": stmt.excluded.wait_sec,
            "talk_sec": stmt.excluded.talk_sec,
            "answered": stmt.excluded.answered,
            "raw_payload": stmt.excluded.raw_payload,
            "updated_at": func.now(),
        },
    )
    db.execute(stmt)
    db.commit()
    return len(rows)


def import_window(
    db: Session, settings: TelephonySettings, start: datetime, end: datetime
) -> TelephonyImportResult:
    """Fetch and upsert calls for [start, end] - both naive Moscow-local,
    Zeon's own convention (see zeon_client.fetch_calls)."""
    if settings.provider != PROVIDER_ZEON:
        raise TelephonyImportError(f"Unsupported telephony provider: {settings.provider!r}")

    zeon_settings = zeon_settings_from(settings)
    try:
        calls = zeon_client.fetch_calls(zeon_settings, start, end)
    except ZeonError as exc:
        raise TelephonyImportError(str(exc)) from exc

    upserted = _upsert_calls(db, settings.provider, calls)
    return TelephonyImportResult(fetched=len(calls), upserted=upserted)


def import_recent(
    db: Session, settings: TelephonySettings, lookback_hours: int
) -> TelephonyImportResult:
    """Convenience wrapper for the periodic relay (services/telephony_relay.py):
    imports [now - lookback_hours, now], in Moscow-local time."""
    now_msk = datetime.now(UTC).astimezone(_MSK).replace(tzinfo=None)
    start = now_msk - timedelta(hours=lookback_hours)
    return import_window(db, settings, start, now_msk)
