"""Background poller for IP-телефония (see services/telephony_import_service.py).

Unlike services/yandex_relay.py (an optional module gated by an env var,
started only for clients whose network can't reach this backend directly),
telephony has no such constraint - Zeon is reachable over plain HTTPS from
here - so this loop always runs (see app/main.py); whether it actually does
anything is controlled entirely by the operator-editable TelephonySettings
row (Settings -> IP-телефония: "Включить" + "Как часто собирать статистику"),
never a redeploy/env var, per the whole point of that settings table.
"""

from __future__ import annotations

import asyncio
import math

import structlog

from app.db.session import SessionLocal
from app.services.telephony_import_service import TelephonyImportError, import_recent
from app.services.telephony_settings_service import get_telephony_settings

logger = structlog.get_logger(__name__)

# How often the loop re-checks TelephonySettings while telephony is
# disabled (or has no schedule configured yet) - short enough that turning
# it on in Settings takes effect without a restart, without polling Zeon
# itself in the meantime.
IDLE_RECHECK_SECONDS = 300

# Every import window looks back further than the configured interval so a
# transient failure or a slow cycle doesn't leave a permanent gap - a missed
# cycle gets picked up again on the next successful one - and so a missed
# call near the edge of one window has more of its 24h callback outcome
# already on hand next time telephony_stats_service re-reads it.
# import_recent's own window is still expressed in hours (see
# telephony_import_service.import_recent) - unrelated to the interval's own
# unit, so the minutes -> hours conversion below is only for that call.
LOOKBACK_MULTIPLIER = 2
MIN_LOOKBACK_HOURS = 2


async def poll_once() -> float:
    """Runs one import cycle if telephony is enabled and scheduled.
    Returns the number of seconds the caller should sleep before the next
    cycle - kept as a return value (not read from module state) so this is
    trivially testable without mocking asyncio.sleep."""
    db = SessionLocal()
    try:
        settings = get_telephony_settings(db)
        if not settings.enabled or not settings.poll_interval_minutes:
            return IDLE_RECHECK_SECONDS

        lookback_hours = max(
            MIN_LOOKBACK_HOURS,
            math.ceil(settings.poll_interval_minutes * LOOKBACK_MULTIPLIER / 60),
        )
        try:
            result = await asyncio.to_thread(import_recent, db, settings, lookback_hours)
            logger.info(
                "telephony_relay_import_completed",
                fetched=result.fetched,
                upserted=result.upserted,
                lookback_hours=lookback_hours,
            )
        except TelephonyImportError as exc:
            logger.error("telephony_relay_import_failed", error=str(exc))
        return max(60, settings.poll_interval_minutes * 60)
    finally:
        db.close()


async def run_relay_loop() -> None:
    logger.info("telephony_relay_started", idle_recheck_seconds=IDLE_RECHECK_SECONDS)
    while True:
        sleep_seconds = IDLE_RECHECK_SECONDS
        try:
            sleep_seconds = await poll_once()
        except Exception as exc:  # noqa: BLE001 - never let the poll loop die
            logger.error("telephony_relay_unexpected_error", error=str(exc))
        await asyncio.sleep(sleep_seconds)
