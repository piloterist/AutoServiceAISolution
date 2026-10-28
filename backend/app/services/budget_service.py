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
from app.services import finance_service
from app.services.cockpit_service import (
    _closed_revenue,
    _closed_revenue_lines,
    _mapped_source_departments,
    _payments,
    period_bounds,
)
from app.services.order_exclusion import (
    order_exclusion,
)
from app.services.settings_service import get_app_settings, revenue_excluded_repair_types

# "Расходы" is no longer typed in here: it is the sum of the cost items entered on
# Финансы -> Расходы (product ask, 2026-10-26), so only the plan stays editable.
BUDGET_FIELDS = ("plan_revenue",)

# Repair type behind "Выручка факт основные" (product ask, 2026-10-26). The
# insurance one comes from AppSettings.insurance_repair_type.
MAIN_REPAIR_TYPE = "Текущий"


@dataclass
class BudgetMonth:
    month: int
    plan_revenue: Decimal
    fact_revenue_insurance: Decimal
    # ... and its parts (product ask, 2026-10-28): the labor and part lines of the
    # same work orders - they should add up to the row above.
    fact_revenue_insurance_labor: Decimal
    fact_revenue_insurance_parts: Decimal
    fact_revenue_main: Decimal
    fact_revenue_main_labor: Decimal
    fact_revenue_main_parts: Decimal
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
    exclusion = order_exclusion(app_settings)

    workshops = db.execute(
        select(Workshop, Department.name)
        .join(Department, Department.id == Workshop.department_id)
        .order_by(Department.name, Workshop.workshop_type)
    ).all()

    expense_totals = finance_service.monthly_expense_totals(db, year)
    insurance_types = (
        [app_settings.insurance_repair_type] if app_settings.insurance_repair_type else []
    )
    excluded_types = revenue_excluded_repair_types(app_settings)

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
            common = dict(
                source_departments=source_departments,
                period_start=period_start,
                period_end=period_end,
                revenue_statuses=revenue_statuses,
                exclusion=exclusion,
                excluded_repair_types=excluded_types,
            )
            fact_insurance = _closed_revenue(db, only_repair_types=insurance_types, **common)
            fact_main = _closed_revenue(db, only_repair_types=[MAIN_REPAIR_TYPE], **common)
            fact_revenue = fact_insurance + fact_main
            insurance_kwargs = dict(common, only_repair_types=insurance_types)
            main_kwargs = dict(common, only_repair_types=[MAIN_REPAIR_TYPE])
            insurance_labor = _closed_revenue_lines(db, kind="labor", **insurance_kwargs)
            insurance_parts = _closed_revenue_lines(db, kind="parts", **insurance_kwargs)
            main_labor = _closed_revenue_lines(db, kind="labor", **main_kwargs)
            main_parts = _closed_revenue_lines(db, kind="parts", **main_kwargs)
            payments = _payments(
                db,
                source_departments=source_departments,
                period_start=period_start,
                period_end=period_end,
                exclusion=exclusion,
            )
            entry = entries.get((workshop.id, month))
            plan_revenue = (entry.plan_revenue if entry else None) or Decimal("0")
            expenses = expense_totals.get((workshop.id, month), Decimal("0"))
            months.append(
                BudgetMonth(
                    month=month,
                    plan_revenue=plan_revenue,
                    fact_revenue_insurance=fact_insurance,
                    fact_revenue_insurance_labor=insurance_labor,
                    fact_revenue_insurance_parts=insurance_parts,
                    fact_revenue_main=fact_main,
                    fact_revenue_main_labor=main_labor,
                    fact_revenue_main_parts=main_parts,
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
        raise ValueError(
            "Это поле нельзя менять вручную: расходы считаются по статьям затрат "
            "(Финансы → Расходы)"
            if field == "expenses"
            else f"Unknown budget field: {field}"
        )
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
