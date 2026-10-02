"""Background poller that automatically transcribes (and, if enabled,
classifies) answered calls - see services/call_transcription_service.py.

Same always-running, settings-gated shape as services/telephony_relay.py
(not services/call_recording_service.py's own manual-button pipeline,
which this doesn't touch): whether this does anything is controlled
entirely by the operator-editable TelephonySettings row (Settings ->
IP-телефония), never a redeploy. Runs a bit less often than the stats
import by default (product ask, 2026-10-02: "с той же периодичностью или
чуть реже... раз в 5-10 минут" - recordings/transcripts need a few minutes
to actually become available on Zeon's side after a call ends).
"""

from __future__ import annotations

import asyncio

import structlog

from app.db.session import SessionLocal
from app.services.call_transcription_service import CallTranscriptionError, process_pending_calls
from app.services.telephony_settings_service import get_telephony_settings

logger = structlog.get_logger(__name__)

# How often the loop re-checks TelephonySettings while telephony is off -
# same reasoning/value as telephony_relay.IDLE_RECHECK_SECONDS.
IDLE_RECHECK_SECONDS = 300

# Fixed, not a new settings field - the operator asked for "5-10 минут",
# not a tunable schedule; 600s sits at the loose end of that on purpose
# (gives Zeon's own recording a few extra minutes to actually land before
# this looks for it, so a call isn't marked failed just because its audio
# wasn't ready yet during the one cycle that happened to run right after
# the call ended - find_pending_calls() just leaves it for the next cycle
# regardless, but there's no reason to pay for near-misses).
POLL_INTERVAL_SECONDS = 600

# Bounds how many calls one cycle takes on - a large backlog (e.g. right
# after first turning this on) clears over several cycles instead of one
# cycle blocking the loop for an unbounded amount of time.
MAX_CALLS_PER_CYCLE = 20


async def poll_once() -> float:
    """Runs one transcription cycle if telephony is enabled. Returns the
    number of seconds the caller should sleep before the next cycle - see
    telephony_relay.poll_once for the same pattern/reasoning."""
    db = SessionLocal()
    try:
        settings = get_telephony_settings(db)
        # Gated on classify_calls_enabled, not just the base telephony
        # `enabled` switch - this is a separate, explicit opt-in (an extra
        # paid SpeechKit+YandexGPT call per answered call), off by default
        # even when telephony stats import itself is on.
        if not settings.enabled or not settings.classify_calls_enabled:
            return IDLE_RECHECK_SECONDS

        try:
            stats = await asyncio.to_thread(
                process_pending_calls, db, settings, MAX_CALLS_PER_CYCLE
            )
            logger.info(
                "call_transcription_relay_cycle_completed",
                transcribed=stats.transcribed,
                classified=stats.classified,
                failed=stats.failed,
                errors=stats.errors,
            )
        except CallTranscriptionError as exc:
            logger.error("call_transcription_relay_not_configured", error=str(exc))
        return POLL_INTERVAL_SECONDS
    finally:
        db.close()


async def run_relay_loop() -> None:
    logger.info(
        "call_transcription_relay_started",
        idle_recheck_seconds=IDLE_RECHECK_SECONDS,
        poll_interval_seconds=POLL_INTERVAL_SECONDS,
    )
    while True:
        sleep_seconds = IDLE_RECHECK_SECONDS
        try:
            sleep_seconds = await poll_once()
        except Exception as exc:  # noqa: BLE001 - never let the poll loop die
            logger.error("call_transcription_relay_unexpected_error", error=str(exc))
        await asyncio.sleep(sleep_seconds)
