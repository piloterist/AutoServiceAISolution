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
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.budget_entry import BudgetEntry
from app.models.department import Department
from app.models.work_order import WorkOrder
from app.models.work_order_invoice import WorkOrderInvoice
from app.models.workshop import Workshop
from app.services import finance_service
from app.services.cockpit_service import (
    MSK,
    _closed_revenue,
    _closed_revenue_filters,
    _closed_revenue_lines,
    _mapped_source_departments,
    _payments,
    period_bounds,
)
from app.services.internal_order_rules import is_physical_person
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

# «Просрочено» (product ask, 2026-11-26): a revenue order not paid in full is overdue when, by
# today (Moscow), the days below have passed - for an individual since the closing date (no
# payment the next day), for a company since the invoice date (21 days; no invoice - the
# closing date). Same individual/company heuristic as the work orders list.
OVERDUE_DAYS_INDIVIDUAL = 1
OVERDUE_DAYS_LEGAL = 21


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
    # Выручка общая = страховые + основные (product ask, 2026-11-25) is `fact_revenue`;
    # `revenue_unpaid` (Без оплат) = the remaining debts of the orders not paid in full (differs
    # from fact_revenue - revenue_paid only by the overpayments of other orders).
    revenue_unpaid: Decimal
    # ... split by the overdue rule above: revenue_overdue + revenue_not_due == revenue_unpaid.
    revenue_overdue: Decimal
    revenue_not_due: Decimal
    # Оплачено (product ask, 2026-11-25): how much of the work orders that make up
    # fact_revenue is paid (their WorkOrder.paid_amount, the current snapshot) - unlike
    # `payments`, which is any money received in the month, by payment date.
    revenue_paid: Decimal
    payments: Decimal
    money: Decimal


@dataclass
class BudgetWorkshopRow:
    workshop_id: uuid.UUID
    workshop_label: str  # "<Подразделение> — <Тип цеха>", same shape as Cockpit's
    months: list[BudgetMonth]  # always 12, index 0 = January


def classify_unpaid_orders(
    db: Session, filters: list, now: datetime
) -> list[tuple[uuid.UUID, Decimal, bool]]:
    """(id, unpaid amount, overdue) for every order of `filters` not paid in full."""
    invoice_date = (
        select(func.min(WorkOrderInvoice.document_date))
        .where(WorkOrderInvoice.work_order_id == WorkOrder.id)
        .scalar_subquery()
    )
    paid = func.coalesce(WorkOrder.paid_amount, 0)
    rows = db.execute(
        select(
            WorkOrder.id,
            WorkOrder.customer_name,
            WorkOrder.closed_date,
            WorkOrder.amount,
            paid,
            invoice_date,
        ).where(*filters, paid < WorkOrder.amount)
    ).all()
    today = now.astimezone(MSK).date()
    result: list[tuple[uuid.UUID, Decimal, bool]] = []
    for order_id, customer, closed, amount, paid_amount, invoiced in rows:
        individual = is_physical_person(customer)
        base = closed if individual or invoiced is None else invoiced
        days = OVERDUE_DAYS_INDIVIDUAL if individual else OVERDUE_DAYS_LEGAL
        overdue = today >= base.astimezone(MSK).date() + timedelta(days=days)
        result.append((order_id, Decimal(amount) - Decimal(paid_amount), overdue))
    return result


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
            revenue_paid = db.execute(
                select(func.coalesce(func.sum(WorkOrder.paid_amount), 0)).where(
                    *_closed_revenue_filters(
                        **common, only_repair_types=[*insurance_types, MAIN_REPAIR_TYPE]
                    )
                )
            ).scalar_one()
            unpaid_orders = classify_unpaid_orders(
                db,
                _closed_revenue_filters(
                    **common, only_repair_types=[*insurance_types, MAIN_REPAIR_TYPE]
                ),
                now,
            )
            revenue_unpaid = sum((debt for _, debt, _ in unpaid_orders), Decimal(0))
            revenue_overdue = sum((debt for _, debt, late in unpaid_orders if late), Decimal(0))
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
                    revenue_paid=Decimal(revenue_paid),
                    revenue_unpaid=revenue_unpaid,
                    revenue_overdue=revenue_overdue,
                    revenue_not_due=revenue_unpaid - revenue_overdue,
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


def fact_order_filters(
    db: Session,
    *,
    year: int,
    month: int,
    kind: str,
    workshop_id: uuid.UUID | None = None,
    now: datetime | None = None,
    year_to: int | None = None,
    month_to: int | None = None,
) -> list:
    """Условия отбора заказ-нарядов ячейки «Выручка факт страховые» (kind="insurance") или
    «Выручка факт основные» (kind="main"), «Выручка общая» (kind="all") или «Без оплат»
    (kind="unpaid": неоплаченные полностью заказ-наряды выручки) за месяц: те же фильтры, что
    у суммы в get_budget_year (_closed_revenue_filters). workshop_id не задан - «Вся компания»:
    отделы всех цехов вместе, как и сумма в таблице (заказ-наряды без привязки к цеху в неё не
    входят)."""
    if kind not in ("insurance", "main", "all", "unpaid", "overdue", "not_due"):
        raise ValueError(f"Unknown kind: {kind}")
    now = now or datetime.now(UTC)
    app_settings = get_app_settings(db)
    if workshop_id is not None:
        source_departments = _mapped_source_departments(db, workshop_id=workshop_id)
    else:
        source_departments = []
        for workshop_ in db.scalars(select(Workshop)):
            source_departments.extend(_mapped_source_departments(db, workshop_id=workshop_.id))
        source_departments = sorted(set(source_departments))
    insurance_types = (
        [app_settings.insurance_repair_type] if app_settings.insurance_repair_type else []
    )
    if kind == "insurance":
        only_types = insurance_types
    elif kind == "main":
        only_types = [MAIN_REPAIR_TYPE]
    else:  # all / unpaid / overdue / not_due: both revenue rows together
        only_types = [*insurance_types, MAIN_REPAIR_TYPE]
    period_start, period_end = period_bounds(now, year=year, month=month)
    if year_to is not None and month_to is not None:
        # Столбец ИТОГО: период из нескольких месяцев подряд - от начала первого до конца
        # последнего (те же границы, что у сумм отдельных месяцев).
        period_end = period_bounds(now, year=year_to, month=month_to)[1]
    filters = _closed_revenue_filters(
        source_departments=source_departments,
        period_start=period_start,
        period_end=period_end,
        revenue_statuses=get_settings().revenue_statuses_list,
        exclusion=order_exclusion(app_settings),
        excluded_repair_types=revenue_excluded_repair_types(app_settings),
        only_repair_types=only_types,
    )
    if kind == "unpaid":
        # Без оплат: the orders of the revenue not paid in full - exactly the ones whose
        # remaining debts the row sums up.
        filters.append(func.coalesce(WorkOrder.paid_amount, 0) < WorkOrder.amount)
    elif kind in ("overdue", "not_due"):
        # Просрочено / Ожидание: the unpaid orders split by the overdue rule (a Python
        # heuristic - individual or company - so the ids are picked here, not in SQL).
        wanted = kind == "overdue"
        classified = classify_unpaid_orders(db, filters, now)
        filters.append(WorkOrder.id.in_([i for i, _, overdue in classified if overdue == wanted]))
    return filters
