"""Раз в минуту: продлевает записи планировщика, пока машина стоит в боксе, и закрывает ошибки
«нет заказ-наряда», когда заказ-наряд появился. Логика - в services/bay_planner.py.

Та же форма, что у services/planner_match_relay.py: фоновая задача asyncio в этом же процессе.
Работает всегда: пока боксов нет, цикл дешёвый (два пустых запроса).
"""

from __future__ import annotations

import asyncio

import structlog

from app.db.session import SessionLocal
from app.services import bay_planner

logger = structlog.get_logger(__name__)

INTERVAL_SECONDS = 60


def run_once() -> tuple[int, int]:
    db = SessionLocal()
    try:
        return bay_planner.tick(db)
    finally:
        db.close()


async def run_relay_loop() -> None:
    logger.info("bay_planner_relay_started", interval_seconds=INTERVAL_SECONDS)
    while True:
        try:
            extended, resolved = await asyncio.to_thread(run_once)
            if extended or resolved:
                logger.info("bay_planner_relay_cycle", extended=extended, resolved=resolved)
        except Exception as exc:  # noqa: BLE001 - never let the loop die
            logger.error("bay_planner_relay_unexpected_error", error=str(exc))
        await asyncio.sleep(INTERVAL_SECONDS)
