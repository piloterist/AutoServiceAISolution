"""«Аллоцировать внешние» (Специфика PanMotors, product ask 2026-11-26).

Normally the revenue of an insurance order goes to the workshop of its own department. With
AppSettings.allocate_external on, the Бюджеты page looks at the internal orders of the same
car (by VIN, WorkOrder.car_key) and split the insurance order's amounts between the workshops
they are written out to in proportion to their sums; when that is one workshop, it gets the
whole order, even if it is not the order's own. An order with no internal orders stays where
it is. Only orders of a mapped department are split, so the company-wide total
never changes - the shares of an order always add up to the order.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.work_order import WorkOrder
from app.models.work_order_line import WorkOrderLaborLine, WorkOrderPartLine
from app.models.workshop_source_department import WorkshopSourceDepartment
from app.services.cockpit_service import _closed_revenue_filters
from app.services.order_exclusion import OrderExclusion

CENT = Decimal("0.01")

# An internal order with this status was refused by the client - it carries no weight.
REFUSED_STATUS = "Отказ"

# order id -> [(workshop id, fraction)], fractions add up to 1
Split = dict[uuid.UUID, list[tuple[uuid.UUID, Decimal]]]


@dataclass
class WorkshopShare:
    """What the split insurance orders add to one workshop in a period."""

    revenue: Decimal = Decimal(0)
    labor: Decimal = Decimal(0)
    parts: Decimal = Decimal(0)
    paid: Decimal = Decimal(0)
    unpaid: Decimal = Decimal(0)
    overdue: Decimal = Decimal(0)


def split_insurance_orders(
    db: Session,
    *,
    period_start: datetime,
    period_end: datetime,
    revenue_statuses: list[str],
    exclusion: OrderExclusion | None,
    excluded_repair_types: list[str] | None,
    insurance_types: list[str],
) -> Split:
    """The insurance revenue orders of the period that are moved to / split between the
    workshops of their internal orders."""
    if not insurance_types:
        return {}
    dept_workshop = dict(
        db.execute(
            select(WorkshopSourceDepartment.source_department, WorkshopSourceDepartment.workshop_id)
        ).all()
    )
    if not dept_workshop:
        return {}
    filters = _closed_revenue_filters(
        source_departments=list(dept_workshop),
        period_start=period_start,
        period_end=period_end,
        revenue_statuses=revenue_statuses,
        exclusion=exclusion,
        excluded_repair_types=excluded_repair_types,
        only_repair_types=insurance_types,
    )
    orders = db.execute(
        select(WorkOrder.id, WorkOrder.car_key).where(*filters, WorkOrder.car_key.is_not(None))
    ).all()
    if not orders:
        return {}
    car_keys = {car for _, car in orders}
    weights: dict[str, dict[uuid.UUID, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    internal = db.execute(
        select(WorkOrder.car_key, WorkOrder.department, func.sum(WorkOrder.amount))
        .where(
            WorkOrder.is_internal.is_(True),
            WorkOrder.amount > 0,
            or_(WorkOrder.status.is_(None), WorkOrder.status != REFUSED_STATUS),
            WorkOrder.car_key.in_(car_keys),
        )
        .group_by(WorkOrder.car_key, WorkOrder.department)
    ).all()
    for car, department, total in internal:
        workshop_id = dept_workshop.get(department)
        if workshop_id is not None:
            weights[car][workshop_id] += Decimal(total)
    split: Split = {}
    for order_id, car in orders:
        by_workshop = weights.get(car)
        if not by_workshop:
            continue
        total = sum(by_workshop.values(), Decimal(0))
        split[order_id] = [(ws, w / total) for ws, w in sorted(by_workshop.items())]
    return split


def _shares(value: Decimal, fractions: list[tuple[uuid.UUID, Decimal]]) -> list[Decimal]:
    """`value` cut by the fractions to the kopeck; the last share takes the remainder."""
    parts = [(value * fraction).quantize(CENT) for _, fraction in fractions[:-1]]
    return [*parts, value - sum(parts, Decimal(0))]


def workshop_shares(
    db: Session, split: Split, unpaid: list[tuple[uuid.UUID, Decimal, bool]]
) -> dict[uuid.UUID, WorkshopShare]:
    """The split orders' amounts, lines, payments and debts cut between the workshops.
    `unpaid` is budget_service.classify_unpaid_orders for the split orders."""
    if not split:
        return {}
    ids = list(split)
    amounts = {
        order_id: (Decimal(amount), Decimal(paid or 0))
        for order_id, amount, paid in db.execute(
            select(WorkOrder.id, WorkOrder.amount, WorkOrder.paid_amount).where(
                WorkOrder.id.in_(ids)
            )
        )
    }
    lines: dict[str, dict[uuid.UUID, Decimal]] = {}
    for kind, line in (("labor", WorkOrderLaborLine), ("parts", WorkOrderPartLine)):
        lines[kind] = {
            order_id: Decimal(total)
            for order_id, total in db.execute(
                select(line.work_order_id, func.sum(func.coalesce(line.total_amount, line.amount)))
                .where(line.work_order_id.in_(ids))
                .group_by(line.work_order_id)
            )
        }
    debts = {order_id: (debt, late) for order_id, debt, late in unpaid}

    result: dict[uuid.UUID, WorkshopShare] = defaultdict(WorkshopShare)

    def add(order_id: uuid.UUID, attr: str, value: Decimal) -> None:
        for (workshop_id, _), part in zip(
            split[order_id], _shares(value, split[order_id]), strict=True
        ):
            setattr(result[workshop_id], attr, getattr(result[workshop_id], attr) + part)

    for order_id in ids:
        amount, paid = amounts.get(order_id, (Decimal(0), Decimal(0)))
        add(order_id, "revenue", amount)
        add(order_id, "paid", paid)
        add(order_id, "labor", lines["labor"].get(order_id, Decimal(0)))
        add(order_id, "parts", lines["parts"].get(order_id, Decimal(0)))
        debt, late = debts.get(order_id, (Decimal(0), False))
        add(order_id, "unpaid", debt)
        add(order_id, "overdue", debt if late else Decimal(0))
    return dict(result)
