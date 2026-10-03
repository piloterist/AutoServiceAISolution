"""Бюджет page: plan/fact revenue, expenses, profit, payments and money per
workshop, per calendar month of a given year.

"Выручка план" and "Расходы" are the only manually-entered numbers (see
models/budget_entry.py - a cell nobody has edited yet reads back as 0, not
stored). Everything else is computed the same way Cockpit already computes
a single period's revenue/payments (see services/cockpit_service.py) - this
module reuses that module's own (underscore-"private" but same codebase,
same bounded context) filtering helpers rather than re-deriving the
workshop -> source-department mapping and revenue-status/internal-exclusion
rules a second time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.budget_entry import BudgetEntry
from app.models.department import Department
from app.models.workshop import Workshop
from app.services.cockpit_service import (
    _closed_revenue,
    _mapped_source_departments,
    _payments,
    period_bounds,
)
from app.services.settings_service import get_app_settings

BUDGET_FIELDS = ("plan_revenue", "expenses")


@dataclass
class BudgetMonth:
    month: int
    plan_revenue: Decimal
    fact_revenue: Decimal
    expenses: Decimal
    profit: Decimal
    payments: Decimal
    money: Decimal


@dataclass
class BudgetWorkshopRow:
    workshop_id: uuid.UUID
    workshop_label: str  # "<Подразделение> — <Тип цеха>", same shape as Cockpit's
    months: list[BudgetMonth]  # always 12, index 0 = January


def get_budget_year(
    db: Session, year: int, *, now: datetime | None = None
) -> list[BudgetWorkshopRow]:
    now = now or datetime.now(UTC)
    settings = get_settings()
    app_settings = get_app_settings(db)
    revenue_statuses = settings.revenue_statuses_list
    exclude_internal = app_settings.exclude_internal_orders

    workshops = db.execute(
        select(Workshop, Department.name)
        .join(Department, Department.id == Workshop.department_id)
        .order_by(Department.name, Workshop.workshop_type)
    ).all()

    entries = {
        (entry.workshop_id, entry.month): entry
        for entry in db.scalars(select(BudgetEntry).where(BudgetEntry.year == year))
    }

    rows: list[BudgetWorkshopRow] = []
    for workshop, department_name in workshops:
        source_departments = _mapped_source_departments(db, workshop_id=workshop.id)
        months: list[BudgetMonth] = []
        for month in range(1, 13):
            period_start, period_end = period_bounds(now, year=year, month=month)
            fact_revenue = _closed_revenue(
                db,
                source_departments=source_departments,
                period_start=period_start,
                period_end=period_end,
                revenue_statuses=revenue_statuses,
                exclude_internal=exclude_internal,
            )
            payments = _payments(
                db,
                source_departments=source_departments,
                period_start=period_start,
                period_end=period_end,
                exclude_internal=exclude_internal,
            )
            entry = entries.get((workshop.id, month))
            plan_revenue = (entry.plan_revenue if entry else None) or Decimal("0")
            expenses = (entry.expenses if entry else None) or Decimal("0")
            months.append(
                BudgetMonth(
                    month=month,
                    plan_revenue=plan_revenue,
                    fact_revenue=fact_revenue,
                    expenses=expenses,
                    profit=fact_revenue - expenses,
                    payments=payments,
                    money=payments - expenses,
                )
            )
        rows.append(
            BudgetWorkshopRow(
                workshop_id=workshop.id,
                workshop_label=f"{department_name} — {workshop.workshop_type}",
                months=months,
            )
        )
    return rows


def set_budget_value(
    db: Session, *, workshop_id: uuid.UUID, year: int, month: int, field: str, value: Decimal
) -> BudgetEntry:
    if field not in BUDGET_FIELDS:
        raise ValueError(f"Unknown budget field: {field}")
    entry = db.scalar(
        select(BudgetEntry).where(
            BudgetEntry.workshop_id == workshop_id,
            BudgetEntry.year == year,
            BudgetEntry.month == month,
        )
    )
    if entry is None:
        entry = BudgetEntry(workshop_id=workshop_id, year=year, month=month)
        db.add(entry)
    setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    return entry
