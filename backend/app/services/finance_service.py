"""Финансы: the cost-item directory (Настройки -> Финансы) and the monthly
expenses per workshop (Финансы -> Расходы).

Rules enforced here, not in the page:
- an amount can be entered only for an ACTIVE cost item; an inactive one is
  shown (with what it already holds) but locked;
- a cost item that already has amounts cannot be deleted - set it inactive
  instead (the figures stay in the Бюджет totals);
- the Бюджет "Расходы" row is the sum of a workshop's cost items for the
  month (see budget_service.get_budget_year).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.cost_expense import CostExpense
from app.models.cost_item import CostItem
from app.models.department import Department
from app.models.workshop import Workshop

ZERO = Decimal("0")


class FinanceError(Exception):
    """Base class - the endpoint maps each subclass to an HTTP status."""


class FinanceNotFound(FinanceError):
    pass


class FinanceConflict(FinanceError):
    pass


class FinanceInvalid(FinanceError):
    pass


# ---- cost items ---------------------------------------------------------------


def list_cost_items(db: Session) -> list[CostItem]:
    return list(db.scalars(select(CostItem).order_by(CostItem.sort_order, CostItem.name)))


def create_cost_item(db: Session, *, name: str, is_active: bool) -> CostItem:
    last = db.scalar(select(func.coalesce(func.max(CostItem.sort_order), 0)))
    item = CostItem(name=name, is_active=is_active, sort_order=int(last or 0) + 1)
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise FinanceConflict("Статья с таким наименованием уже есть") from exc
    db.refresh(item)
    return item


def update_cost_item(db: Session, item_id: uuid.UUID, *, name: str, is_active: bool) -> CostItem:
    item = db.get(CostItem, item_id)
    if item is None:
        raise FinanceNotFound("Статья затрат не найдена")
    item.name = name
    item.is_active = is_active
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise FinanceConflict("Статья с таким наименованием уже есть") from exc
    db.refresh(item)
    return item


def reorder_cost_items(db: Session, ids: list[uuid.UUID]) -> list[CostItem]:
    """Sets the hand-made order: the given ids first, in that order; any item
    not listed keeps its relative order after them."""
    if len(set(ids)) != len(ids):
        raise FinanceInvalid("Повторяющиеся статьи в порядке")
    items = list_cost_items(db)
    by_id = {item.id: item for item in items}
    if any(item_id not in by_id for item_id in ids):
        raise FinanceNotFound("Статья затрат не найдена")
    ordered = [by_id[item_id] for item_id in ids] + [i for i in items if i.id not in set(ids)]
    for position, item in enumerate(ordered, start=1):
        item.sort_order = position
    db.commit()
    return list_cost_items(db)


def delete_cost_item(db: Session, item_id: uuid.UUID) -> None:
    item = db.get(CostItem, item_id)
    if item is None:
        raise FinanceNotFound("Статья затрат не найдена")
    used = db.scalar(
        select(func.count()).select_from(CostExpense).where(CostExpense.cost_item_id == item_id)
    )
    if used:
        raise FinanceConflict(
            "По статье уже есть внесённые расходы — удалить нельзя, сделайте её неактивной"
        )
    db.delete(item)
    db.commit()


# ---- expenses -----------------------------------------------------------------


def get_expenses_year(db: Session, year: int) -> dict:
    """Items (active ones, plus inactive ones that hold amounts this year),
    and per workshop the 12 monthly amounts of each item and the totals."""
    amounts: dict[tuple[uuid.UUID, uuid.UUID, int], Decimal] = {}
    for expense in db.scalars(select(CostExpense).where(CostExpense.year == year)):
        amounts[(expense.workshop_id, expense.cost_item_id, expense.month)] = expense.amount
    used_item_ids = {item_id for (_, item_id, _) in amounts}

    items = [item for item in list_cost_items(db) if item.is_active or item.id in used_item_ids]

    workshops = db.execute(
        select(Workshop, Department.name)
        .join(Department, Department.id == Workshop.department_id)
        .order_by(Department.name, Workshop.workshop_type)
    ).all()

    result = []
    for workshop, department_name in workshops:
        rows = []
        totals = [ZERO] * 12
        for item in items:
            months = [amounts.get((workshop.id, item.id, month), ZERO) for month in range(1, 13)]
            for index, value in enumerate(months):
                totals[index] += value
            rows.append({"cost_item_id": item.id, "months": months})
        result.append(
            {
                "workshop_id": workshop.id,
                "workshop_label": f"{department_name} — {workshop.workshop_type}",
                "rows": rows,
                "totals": totals,
            }
        )
    return {"year": year, "items": items, "workshops": result}


def monthly_expense_totals(db: Session, year: int) -> dict[tuple[uuid.UUID, int], Decimal]:
    """(workshop_id, month) -> sum over every cost item - what the Бюджет
    "Расходы" row shows."""
    rows = db.execute(
        select(CostExpense.workshop_id, CostExpense.month, func.sum(CostExpense.amount))
        .where(CostExpense.year == year)
        .group_by(CostExpense.workshop_id, CostExpense.month)
    ).all()
    return {(workshop_id, month): Decimal(total or 0) for workshop_id, month, total in rows}


def set_expense(
    db: Session,
    *,
    cost_item_id: uuid.UUID,
    workshop_id: uuid.UUID,
    year: int,
    month: int,
    amount: Decimal,
) -> None:
    item = db.get(CostItem, cost_item_id)
    if item is None:
        raise FinanceNotFound("Статья затрат не найдена")
    if not item.is_active:
        raise FinanceInvalid("Статья неактивна — значение менять нельзя")
    if db.get(Workshop, workshop_id) is None:
        raise FinanceNotFound("Цех не найден")
    set_cell(
        db,
        cost_item_id=cost_item_id,
        workshop_id=workshop_id,
        year=year,
        month=month,
        amount=amount,
    )
    db.commit()


def set_cell(
    db: Session,
    *,
    cost_item_id: uuid.UUID,
    workshop_id: uuid.UUID,
    year: int,
    month: int,
    amount: Decimal,
) -> None:
    """Writes one cell WITHOUT committing (the import writes many in one
    transaction); zero clears it. The caller has checked the item is active."""
    cell = db.scalar(
        select(CostExpense).where(
            CostExpense.cost_item_id == cost_item_id,
            CostExpense.workshop_id == workshop_id,
            CostExpense.year == year,
            CostExpense.month == month,
        )
    )
    if amount == 0:
        if cell is not None:
            db.delete(cell)
    elif cell is None:
        db.add(
            CostExpense(
                cost_item_id=cost_item_id,
                workshop_id=workshop_id,
                year=year,
                month=month,
                amount=amount,
            )
        )
    else:
        cell.amount = amount
