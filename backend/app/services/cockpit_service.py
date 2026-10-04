"""Cockpit: data for the car-dashboard-styled landing page - closed revenue
vs. the selected scope's monthly plan, payments received, and НЗП
(work-in-progress revenue: open work orders close enough to completion to
count toward the month). See app/api/v1/endpoints/cockpit.py for the HTTP
surface.

Scoping: Cockpit's own "Вся компания / конкретный цех" filter is a real
Workshop (app/models/workshop.py - "цех" is literally what this entity is
called throughout this codebase), not the coarser Department. WorkOrder has
no real workshop_id/department_id FK, only a free-text `department` column
sent by 1C - and on real client data those strings are messy and
workshop-type-embedded (e.g. "Кузовной цех (Каховка)", "Слесарный
цех_(ИП Пан)"), not equal to any Department.name at all. Rather than guess
at a name/substring match (which would silently misattribute revenue the
moment a client's 1C strings don't follow a predictable pattern), this
reads an explicit, operator-maintained mapping - see
models/workshop_source_department.py and Settings -> Цеха -> "Соответствие
1С" - from raw `WorkOrder.department` strings to a Workshop (many strings
can map to the same Workshop). Company-wide scope applies no such filter at
all (every work order counts, mapped or not) and instead flags any revenue
whose `department` isn't mapped to *any* Workshop as `has_unattributed_revenue`
- see product spec: "Выручку без привязки к цеху включай в общий итог
компании и явно отмечай проблему привязки".

The monthly *plan* lives on Workshop.target_revenue directly (a real,
already-editable field via Settings -> Цеха) - a specific workshop's plan
is just its own value; the whole-company plan sums target_revenue across
every Workshop, matching the product spec's own definition.

НЗП source data: there is no Слесарный НЗП at all (confirmed product
decision - a Слесарный workshop's НЗП contribution is always 0). Only
Кузовной has one, reading BodyCarStage.end_date for the "Сборка-
Полировка"/"Выдача" stages, scoped directly through BodyCar.workshop_id (a
real FK, unlike WorkOrder) - and only for work orders not yet closed
(WorkOrder.closed_date IS NULL), so a car that's since been closed and
already counted in `revenue` is never also double-counted here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.body_car import BodyCar
from app.models.body_car_stage import BodyCarStage
from app.models.budget_entry import BudgetEntry
from app.models.department import Department
from app.models.work_order import WorkOrder
from app.models.work_order_payment_event import WorkOrderPaymentEvent
from app.models.workshop import Workshop
from app.models.workshop_source_department import WorkshopSourceDepartment
from app.services.settings_service import get_app_settings

# Russia has used a flat UTC+3 with no DST since 2014 - same fixed-offset
# convention already used throughout this codebase (see
# import_service._naive_msk_to_utc and the telephony services), duplicated
# rather than shared since each of those already independently is.
MSK = timezone(timedelta(hours=3))

# "Сборка-Полировка"/"Выдача" from models.planner_constants.BODY_STAGE_TYPES
# - not imported directly (that tuple also lists stages irrelevant here) to
# keep this module's own contract to exactly the two stage names its НЗП
# rule cares about.
_BODY_NZP_STAGES = ("Сборка-Полировка", "Выдача")

_STEP_MULTIPLIERS = (1, 2, 5)
# Covers plans up to 5*10^7 million ₽ (50 trillion ₽) - vastly beyond any
# realistic monthly plan; a fixed, small, obviously-terminating range
# rather than an open-ended search.
_MAX_STEP_EXPONENT = 7


def _candidate_steps() -> list[int]:
    return sorted(m * 10**k for k in range(_MAX_STEP_EXPONENT + 1) for m in _STEP_MULTIPLIERS)


@dataclass
class GaugeScale:
    """One gauge's adaptive scale - see compute_gauge_scale(). All amounts
    in millions of rubles except `marker_fraction`, which is already a
    0..1 position along the arc."""

    step_millions: int
    max_millions: int
    labels_millions: list[int]
    marker_fraction: float  # plan's own position along the arc


MIN_SCALE_INTERVALS = 6


def compute_gauge_scale(plan_rub: Decimal) -> GaugeScale:
    """Deterministic adaptive scale for the revenue gauge - pure function,
    no DB access. Ported from the product spec's algorithm:

        T = план / 1_000_000
        s = minimal step from {1,2,5}x10^k where ceil(T/s) <= 8
        n = max(6, ceil(T/s) + 2)
        M = n * s

    The "+2" headroom alone lets a small plan (or the neutral no-plan
    fallback below) collapse to as few as 2-3 tick intervals, which reads
    as broken on the actual dial rather than sparse (per product feedback:
    "не меньше 6 делений, а то на одно сейчас получилось 3, вообще тупо
    смотрится") - the needle simply sits lower on a wider scale instead.
    The spec's own worked examples (plan -> step/max in millions):
    10->2/14, 16->2/20, 50->10/70, 13->2/18 hit >=6 intervals already and
    are unaffected; 0.5->1/6 (not the original 1/3) is the one this floor
    actually changes - see tests/test_cockpit_service.py.
    """
    t = plan_rub / Decimal(1_000_000)
    steps = _candidate_steps()
    chosen = steps[-1]
    for s in steps:
        n_units = int((t / s).to_integral_value(rounding=ROUND_CEILING))
        if n_units <= 8:
            chosen = s
            break
    n_units = int((t / chosen).to_integral_value(rounding=ROUND_CEILING))
    n = max(MIN_SCALE_INTERVALS, n_units + 2)
    m = n * chosen
    marker_fraction = float(t / m) if m else 0.0
    return GaugeScale(
        step_millions=chosen,
        max_millions=m,
        labels_millions=list(range(0, m + 1, chosen)),
        marker_fraction=marker_fraction,
    )


def period_bounds(
    now: datetime | None = None,
    *,
    year: int | None = None,
    month: int | None = None,
) -> tuple[datetime, datetime]:
    """Moscow-local calendar month bounds (both returned as UTC-aware
    datetimes, ready to compare against timestamptz columns directly).

    `year`/`month` pick which month (both omitted - the default - means the
    current month, per product spec, 2026-09-30: "по умолчанию всегда
    должен показывать текущий"). The *current* month's own end is always
    `now` itself (a running month-to-date total, unchanged from before this
    picker existed); any other month gets its real end-of-month boundary.
    A month that hasn't started yet collapses to an empty [start, start)
    range rather than a negative one - defensive only, the frontend's own
    picker never offers a future month.
    """
    now = now or datetime.now(UTC)
    now_msk = now.astimezone(MSK)
    if year is None or month is None:
        year, month = now_msk.year, now_msk.month
    start_msk = datetime(year, month, 1, tzinfo=MSK)
    if (year, month) == (now_msk.year, now_msk.month):
        return start_msk.astimezone(UTC), now
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    next_start_msk = datetime(next_year, next_month, 1, tzinfo=MSK)
    end = min(next_start_msk.astimezone(UTC), now)
    end = max(end, start_msk.astimezone(UTC))
    return start_msk.astimezone(UTC), end


def _mapped_source_departments(db: Session, *, workshop_id: uuid.UUID | None) -> list[str] | None:
    """Raw WorkOrder.department strings mapped to the given workshop.

    Returns None (meaning "no filter - count everything") only for the
    unrestricted company-wide case (`workshop_id` omitted) -
    revenue/payments company-wide totals must include unattributed work
    orders too, not silently drop them. A specific workshop returns a
    concrete (possibly empty) list.
    """
    if workshop_id is None:
        return None
    query = select(WorkshopSourceDepartment.source_department).where(
        WorkshopSourceDepartment.workshop_id == workshop_id
    )
    return list(db.scalars(query))


def _closed_revenue(
    db: Session,
    *,
    source_departments: list[str] | None,
    period_start: datetime,
    period_end: datetime,
    revenue_statuses: list[str],
    exclude_internal: bool,
) -> Decimal:
    filters = [
        WorkOrder.closed_date.is_not(None),
        WorkOrder.closed_date >= period_start,
        WorkOrder.closed_date < period_end,
    ]
    if source_departments is not None:
        filters.append(WorkOrder.department.in_(source_departments))
    if revenue_statuses:
        filters.append(WorkOrder.status.in_(revenue_statuses))
    if exclude_internal:
        filters.append(WorkOrder.is_internal.is_(False))
    total = db.execute(select(func.sum(WorkOrder.amount)).where(*filters)).scalar_one()
    return total or Decimal("0")


def _has_unattributed_revenue(
    db: Session,
    *,
    period_start: datetime,
    period_end: datetime,
    revenue_statuses: list[str],
    exclude_internal: bool,
) -> bool:
    """Whether any revenue-eligible work order in the whole-company total
    has a `department` value with no Workshop mapping at all - the
    "проблема привязки" the spec asks to flag rather than silently drop
    from (or, worse, wrongly fold into) a specific цех's own total."""
    mapped = select(WorkshopSourceDepartment.source_department)
    filters = [
        WorkOrder.closed_date.is_not(None),
        WorkOrder.closed_date >= period_start,
        WorkOrder.closed_date < period_end,
        or_(WorkOrder.department.is_(None), WorkOrder.department.not_in(mapped)),
    ]
    if revenue_statuses:
        filters.append(WorkOrder.status.in_(revenue_statuses))
    if exclude_internal:
        filters.append(WorkOrder.is_internal.is_(False))
    count = db.execute(select(func.count()).select_from(WorkOrder).where(*filters)).scalar_one()
    return count > 0


def _payments(
    db: Session,
    *,
    source_departments: list[str] | None,
    period_start: datetime,
    period_end: datetime,
    exclude_internal: bool,
) -> Decimal:
    filters = [
        WorkOrderPaymentEvent.paid_at >= period_start,
        WorkOrderPaymentEvent.paid_at < period_end,
    ]
    query = select(func.sum(WorkOrderPaymentEvent.amount))
    if source_departments is not None or exclude_internal:
        query = query.join(WorkOrder, WorkOrder.id == WorkOrderPaymentEvent.work_order_id)
        if source_departments is not None:
            filters.append(WorkOrder.department.in_(source_departments))
        if exclude_internal:
            filters.append(WorkOrder.is_internal.is_(False))
    total = db.execute(query.where(*filters)).scalar_one()
    return total or Decimal("0")


def _budget_plan_revenue(
    db: Session, *, workshop_id: uuid.UUID | None, year: int, month: int
) -> Decimal:
    """Выручка план for this scope's own month, straight from the Бюджет
    page (models/budget_entry.py) rather than Workshop.target_revenue (the
    separate, static plan the gauge's own scale/needle use) - per product
    ask, 2026-10-03, the revenue progress strip's right edge should track
    the Бюджет page's own plan number instead. A specific workshop reads
    its own cell for the month; company-wide sums every workshop's cell (a
    workshop with no entry yet simply contributes 0, same as any missing
    BudgetEntry row)."""
    query = select(func.sum(BudgetEntry.plan_revenue)).where(
        BudgetEntry.year == year, BudgetEntry.month == month
    )
    if workshop_id is not None:
        query = query.where(BudgetEntry.workshop_id == workshop_id)
    total = db.execute(query).scalar_one()
    return total or Decimal("0")


def _receivables(
    db: Session,
    *,
    source_departments: list[str] | None,
    revenue_statuses: list[str],
    exclude_internal: bool,
) -> Decimal:
    """ДЗ (дебиторская задолженность) - a running total, not scoped to a
    period (unlike revenue/payments above): the sum of WorkOrder.debt_amount
    for every closed work order that still owes something.

    Originally this inferred "unpaid" from the ABSENCE of a
    WorkOrderPaymentEvent/WorkOrderInvoice row (see git history before
    2026-10-04) - dropped after a live example (ЗН СЦН0002701, confirmed via
    its own detail page: "Оплачено 100%, Остаток долга 0 ₽") showed that
    rule flagging a fully-paid order as outstanding, because the payment
    that settled it was never recorded as its own work_order_payment_events
    row (and work_order_invoices turned out to have zero rows at all,
    company-wide - invoices from 1C were never wired up). `debt_amount`
    instead is 1C's OWN already-computed running settlement balance
    (ВзаиморасчетыКомпании.Остатки(), see WorkOrder's own docstring) - the
    exact number the Work Order detail page's own "Остаток долга" shows, so
    this can never disagree with what the operator sees on one order up
    close. Still scoped to CLOSED orders only (an open order isn't
    "receivable" yet, per the original product rule), but no longer needs
    the invoice/payment-event tables at all."""
    filters = [WorkOrder.closed_date.is_not(None), WorkOrder.debt_amount > 0]
    if source_departments is not None:
        filters.append(WorkOrder.department.in_(source_departments))
    if revenue_statuses:
        filters.append(WorkOrder.status.in_(revenue_statuses))
    if exclude_internal:
        filters.append(WorkOrder.is_internal.is_(False))
    total = db.execute(select(func.sum(WorkOrder.debt_amount)).where(*filters)).scalar_one()
    return total or Decimal("0")


def _nzp_body(
    db: Session,
    *,
    workshop_id: uuid.UUID | None,
    period_end_date_msk: date,
    exclude_internal: bool,
) -> Decimal:
    """Кузовной НЗП: work orders linked to a BodyCar with a "Сборка-
    Полировка" or "Выдача" этап planned to end on/before period_end (in
    Moscow-local calendar days, matching BodyCarStage.end_date's own plain
    Date type - it carries no time/timezone of its own). A car qualifying
    via both stages, or a work order somehow linked to more than one
    BodyCar, is only counted once (`.distinct()` on work_order_id).
    `workshop_id=None` means every Кузовной workshop (BodyCar.workshop_id
    is a real FK, so no source-department mapping is needed here)."""
    qualifying_work_order_ids = (
        select(BodyCar.work_order_id)
        .join(BodyCarStage, BodyCarStage.body_car_id == BodyCar.id)
        .where(
            BodyCarStage.stage_name.in_(_BODY_NZP_STAGES),
            BodyCarStage.end_date <= period_end_date_msk,
            BodyCar.work_order_id.is_not(None),
        )
        .distinct()
    )
    if workshop_id is not None:
        qualifying_work_order_ids = qualifying_work_order_ids.where(
            BodyCar.workshop_id == workshop_id
        )

    filters = [WorkOrder.id.in_(qualifying_work_order_ids), WorkOrder.closed_date.is_(None)]
    if exclude_internal:
        filters.append(WorkOrder.is_internal.is_(False))
    total = db.execute(select(func.sum(WorkOrder.amount)).where(*filters)).scalar_one()
    return total or Decimal("0")


@dataclass
class PlanResult:
    total_rub: Decimal
    complete: bool  # every workshop in scope has a target_revenue set
    workshop_count: int

    @property
    def usable(self) -> bool:
        """False for "no plan set" (0/null) as well as "incomplete" (spec
        treats both the same: show real revenue, neutral scale)."""
        return self.complete and self.workshop_count > 0 and self.total_rub > 0


def _compute_plan(db: Session, workshop_id: uuid.UUID | None) -> PlanResult:
    query = select(Workshop.target_revenue)
    if workshop_id is not None:
        query = query.where(Workshop.id == workshop_id)
    values = db.scalars(query).all()
    total = sum((v for v in values if v is not None), Decimal("0"))
    complete = len(values) > 0 and all(v is not None for v in values)
    return PlanResult(total_rub=total, complete=complete, workshop_count=len(values))


@dataclass
class GaugeReading:
    scale: GaugeScale  # always present - see get_snapshot()'s neutral-scale fallback
    needle_fraction: float  # 0..1, already clamped
    overflow: bool
    underflow: bool


def _read_gauge(scale: GaugeScale, amount_rub: Decimal) -> GaugeReading:
    max_rub = Decimal(scale.max_millions) * Decimal(1_000_000)
    if amount_rub < 0:
        return GaugeReading(scale=scale, needle_fraction=0.0, overflow=False, underflow=True)
    if max_rub and amount_rub > max_rub:
        return GaugeReading(scale=scale, needle_fraction=1.0, overflow=True, underflow=False)
    fraction = float(amount_rub / max_rub) if max_rub else 0.0
    return GaugeReading(scale=scale, needle_fraction=fraction, overflow=False, underflow=False)


@dataclass
class CockpitSnapshot:
    period_start: datetime
    period_end: datetime
    timezone: str
    workshop_id: uuid.UUID | None
    workshop_label: str | None  # "<Подразделение> — <Тип цеха>", e.g. "Каховка — Кузовной"

    revenue_rub: Decimal
    nzp_rub: Decimal | None  # None when NZP wasn't requested
    effective_revenue_rub: Decimal  # revenue (+ nzp, when requested)
    payments_rub: Decimal
    receivables_rub: Decimal  # ДЗ - a running total, not period-scoped, see _receivables
    budget_plan_revenue_rub: Decimal  # Бюджет page's own "Выручка план" for this month/scope

    plan: PlanResult
    revenue_gauge: GaugeReading
    payments_gauge: GaugeReading

    has_unattributed_revenue: bool


def get_snapshot(
    db: Session,
    *,
    workshop_id: uuid.UUID | None,
    include_nzp: bool,
    year: int | None = None,
    month: int | None = None,
    now: datetime | None = None,
) -> CockpitSnapshot:
    period_start, period_end = period_bounds(now, year=year, month=month)
    settings = get_settings()
    app_settings = get_app_settings(db)
    revenue_statuses = settings.revenue_statuses_list
    exclude_internal = app_settings.exclude_internal_orders

    workshop_label = None
    if workshop_id is not None:
        workshop = db.get(Workshop, workshop_id)
        if workshop is not None:
            department = db.get(Department, workshop.department_id)
            department_name = department.name if department else ""
            workshop_label = f"{department_name} — {workshop.workshop_type}"

    source_departments = _mapped_source_departments(db, workshop_id=workshop_id)

    revenue = _closed_revenue(
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

    receivables = _receivables(
        db,
        source_departments=source_departments,
        revenue_statuses=revenue_statuses,
        exclude_internal=exclude_internal,
    )

    period_start_msk = period_start.astimezone(MSK)
    budget_plan_revenue = _budget_plan_revenue(
        db, workshop_id=workshop_id, year=period_start_msk.year, month=period_start_msk.month
    )

    nzp_total: Decimal | None = None
    if include_nzp:
        # No Слесарный НЗП at all (confirmed product decision) - only
        # _nzp_body contributes, and it's naturally 0 for a Слесарный-only
        # scope: BodyCar.workshop_id never points at a Слесарный workshop,
        # so the query below simply finds nothing to sum for one.
        period_end_date_msk = period_end.astimezone(MSK).date()
        nzp_total = _nzp_body(
            db,
            workshop_id=workshop_id,
            period_end_date_msk=period_end_date_msk,
            exclude_internal=exclude_internal,
        )

    effective_revenue = revenue + (nzp_total or Decimal("0"))

    plan = _compute_plan(db, workshop_id)
    if plan.usable:
        scale = compute_gauge_scale(plan.total_rub)
    else:
        # No usable plan (missing/incomplete): the dial still needs real
        # ticks/numbers and a needle that actually moves - spec asks for a
        # "neutral scale and needle", not an empty face - so the scale is
        # derived from the amounts themselves instead of a plan. Frontend
        # gates the plan-marker triangle on plan.usable, never on whether a
        # scale is present, so this fallback never draws a fake plan mark.
        neutral_anchor = max(effective_revenue, payments, Decimal("0"))
        scale = compute_gauge_scale(neutral_anchor if neutral_anchor > 0 else Decimal(1_000_000))
    revenue_gauge = _read_gauge(scale, effective_revenue)
    payments_gauge = _read_gauge(scale, payments)

    has_unattributed = False
    if workshop_id is None:
        has_unattributed = _has_unattributed_revenue(
            db,
            period_start=period_start,
            period_end=period_end,
            revenue_statuses=revenue_statuses,
            exclude_internal=exclude_internal,
        )

    return CockpitSnapshot(
        period_start=period_start,
        period_end=period_end,
        timezone="Europe/Moscow",
        workshop_id=workshop_id,
        workshop_label=workshop_label,
        revenue_rub=revenue,
        nzp_rub=nzp_total,
        effective_revenue_rub=effective_revenue,
        payments_rub=payments,
        receivables_rub=receivables,
        budget_plan_revenue_rub=budget_plan_revenue,
        plan=plan,
        revenue_gauge=revenue_gauge,
        payments_gauge=payments_gauge,
        has_unattributed_revenue=has_unattributed,
    )
