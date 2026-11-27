"""«Фиктивные» платежи: дубли строк одного платежа (product ask, 2026-11-27).

1С иногда присылает платёж по заказ-наряду несколько раз: тот же документ, та же дата, та же
сумма, разные номера строк - и платежей в «Истории оплат» получается в 2, 3 раза больше суммы ЗН
(200%, 300%). Правило: если у ЗН все платежи на одну и ту же сумму и их общий итог кратен сумме
ЗН (в k раз, k >= 2), то настоящих платежей n / k (при n кратном k) - первые по дате и номеру
строки, остальные помечаются is_fictitious. Фиктивные красные на карточке и нигде не считаются
(services/order_payments.py и суммы по датам исключают их). Пометка пересчитывается при каждом
импорте ЗН, а разовая прогонка по всей базе - `python -m app.services.payment_duplicates`.
"""

from __future__ import annotations

import sys
import uuid
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.work_order import WorkOrder
from app.models.work_order_payment_event import WorkOrderPaymentEvent

TOLERANCE = Decimal("0.01")


def fictitious_ids(order_amount: Decimal, events: list[WorkOrderPaymentEvent]) -> set[uuid.UUID]:
    """The events of one order that are duplicates (empty when the rule does not apply)."""
    n = len(events)
    if n < 2 or order_amount is None or order_amount <= 0:
        return set()
    first = events[0].amount
    if any(event.amount != first for event in events):
        return set()
    k = round(first * n / order_amount)
    if k < 2 or n % k != 0 or abs(first * n - k * order_amount) > TOLERANCE:
        return set()
    ordered = sorted(events, key=lambda e: (e.paid_at, e.line_number, e.source_document_id))
    return {event.id for event in ordered[n // k :]}


def mark_duplicate_payments(
    db: Session, work_order_ids: Iterable[uuid.UUID] | None = None, *, dry_run: bool = False
) -> int:
    """Recomputes is_fictitious for the given orders (all when None); returns how many payment
    lines changed their mark. Does not commit - the caller does (the import commits per chunk)."""
    query = select(WorkOrderPaymentEvent, WorkOrder.amount).join(
        WorkOrder, WorkOrder.id == WorkOrderPaymentEvent.work_order_id
    )
    if work_order_ids is not None:
        ids = list(work_order_ids)
        if not ids:
            return 0
        query = query.where(WorkOrderPaymentEvent.work_order_id.in_(ids))
    by_order: dict[uuid.UUID, list[WorkOrderPaymentEvent]] = defaultdict(list)
    amounts: dict[uuid.UUID, Decimal] = {}
    for event, amount in db.execute(query):
        by_order[event.work_order_id].append(event)
        amounts[event.work_order_id] = Decimal(amount)

    to_mark: list[uuid.UUID] = []
    to_clear: list[uuid.UUID] = []
    for order_id, events in by_order.items():
        wanted = fictitious_ids(amounts[order_id], events)
        for event in events:
            if event.id in wanted and not event.is_fictitious:
                to_mark.append(event.id)
            elif event.id not in wanted and event.is_fictitious:
                to_clear.append(event.id)
    if not dry_run:
        for ids, value in ((to_mark, True), (to_clear, False)):
            if ids:
                db.execute(
                    update(WorkOrderPaymentEvent)
                    .where(WorkOrderPaymentEvent.id.in_(ids))
                    .values(is_fictitious=value)
                )
    return len(to_mark) + len(to_clear)


def main() -> int:  # pragma: no cover - one-off maintenance run
    from app.db.session import SessionLocal

    dry_run = "--apply" not in sys.argv
    with SessionLocal() as db:
        changed = mark_duplicate_payments(db, dry_run=dry_run)
        if not dry_run:
            db.commit()
    print(
        ("Будет изменено (пробный запуск, добавьте --apply): " if dry_run else "Изменено: ")
        + str(changed)
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
