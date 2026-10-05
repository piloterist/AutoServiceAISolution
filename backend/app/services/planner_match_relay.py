"""Background poller that automatically links unlinked Planner records
(WorkshopJob/BodyCar with no work_order_id yet) to a matching ЗН imported
afterward - see services/planner_service.auto_match_planner_records for the
matching rule (phone or VIN, within a 3-day window) and models/app_settings.py
for the settings this reads.

Same always-running, settings-gated shape as services/telephony_relay.py:
whether this does anything is controlled entirely by the operator-editable
AppSettings row (Settings page), never a redeploy.
"""

from __future__ import annotations

import asyncio

import structlog

from app.db.session import SessionLocal
from app.services.planner_service import auto_match_planner_records
from app.services.settings_service import get_app_settings

logger = structlog.get_logger(__name__)

# How often the loop re-checks AppSettings while the feature is off - same
# reasoning/value as telephony_relay.IDLE_RECHECK_SECONDS.
IDLE_RECHECK_SECONDS = 300


async def poll_once() -> float:
    """Runs one auto-match pass if enabled. Returns the number of seconds
    the caller should sleep before the next cycle - see
    telephony_relay.poll_once for the same pattern/reasoning."""
    db = SessionLocal()
    try:
        settings = get_app_settings(db)
        if not settings.planner_auto_match_enabled:
            return IDLE_RECHECK_SECONDS

        stats = await asyncio.to_thread(auto_match_planner_records, db)
        logger.info(
            "planner_match_relay_cycle_completed",
            processed=stats.processed,
            matched=stats.matched,
        )
        return max(60, settings.planner_auto_match_interval_minutes * 60)
    finally:
        db.close()


async def run_relay_loop() -> None:
    logger.info("planner_match_relay_started", idle_recheck_seconds=IDLE_RECHECK_SECONDS)
    while True:
        sleep_seconds = IDLE_RECHECK_SECONDS
        try:
            sleep_seconds = await poll_once()
        except Exception as exc:  # noqa: BLE001 - never let the poll loop die
            logger.error("planner_match_relay_unexpected_error", error=str(exc))
        await asyncio.sleep(sleep_seconds)
