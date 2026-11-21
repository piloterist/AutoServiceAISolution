"""Контроль выгрузки из 1С: если пакета нет дольше двух часов (считаются только часы с 6:00 до
23:00 по Москве), на листе «Ошибки» появляется ошибка; когда пакет пришёл - закрывается сама.

Ночью выгрузки нет по расписанию, поэтому ночное молчание не считается: последний пакет в 22:30
даёт ошибку не в 00:30, а в 07:30 (полчаса вечером плюс полтора часа утром).
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.bay import (
    ISSUE_IMPORT_STALE,
    ISSUE_RESOLVED_AUTO,
    BayIssue,
)
from app.models.import_batch import ImportBatch
from app.services.bay_service import SHOP_TZ

logger = structlog.get_logger(__name__)

ACTOR_NAME = "Контроль выгрузки"
SILENCE_LIMIT = timedelta(hours=2)
WINDOW_START = time(6, 0)
WINDOW_END = time(23, 0)
_BATCH_OK = "success"


def _window_silence(since: datetime, now: datetime) -> timedelta:
    """Сколько из промежутка [since, now] приходится на часы 6:00-23:00 по Москве."""
    since, now = since.astimezone(SHOP_TZ), now.astimezone(SHOP_TZ)
    total = timedelta()
    day = since.date()
    while day <= now.date():
        start = datetime.combine(day, WINDOW_START, SHOP_TZ)
        end = datetime.combine(day, WINDOW_END, SHOP_TZ)
        lo, hi = max(start, since), min(end, now)
        if hi > lo:
            total += hi - lo
        day += timedelta(days=1)
    return total


def check(db: Session, now: datetime | None = None) -> str | None:
    """Открывает или закрывает ошибку. Возвращает "opened" / "resolved" / None."""
    now = now or datetime.now(UTC)
    last = db.scalar(
        select(func.max(ImportBatch.received_at)).where(ImportBatch.status == _BATCH_OK)
    )
    if last is None:
        return None  # пакетов ещё не было вообще: следить не за чем
    stale = _window_silence(last, now) > SILENCE_LIMIT
    open_issue = db.scalars(
        select(BayIssue).where(BayIssue.kind == ISSUE_IMPORT_STALE, BayIssue.resolved_at.is_(None))
    ).first()
    if stale and open_issue is None:
        local_last = last.astimezone(SHOP_TZ).strftime("%d.%m %H:%M")
        db.add(
            BayIssue(
                bay_id=None,
                kind=ISSUE_IMPORT_STALE,
                plate=None,
                message=(
                    f"Из 1С больше 2 часов нет данных (с 6:00 до 23:00). Последний пакет получен "
                    f"{local_last} (МСК). Проверьте выгрузку на сервере 1С: открыт ли сеанс "
                    "пользователя и работает ли задание Планировщика."
                ),
                occurred_at=now,
            )
        )
        db.commit()
        logger.warning("import_stale_issue_opened", last_batch=last.isoformat())
        return "opened"
    if not stale and open_issue is not None:
        open_issue.resolved_at = now
        open_issue.resolution = ISSUE_RESOLVED_AUTO
        open_issue.resolved_by = ACTOR_NAME
        open_issue.resolution_note = "Пакет из 1С получен"
        db.commit()
        logger.info("import_stale_issue_resolved")
        return "resolved"
    return None
