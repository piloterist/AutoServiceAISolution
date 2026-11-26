"""Tests for services/budget_service.py - the Бюджет page's per-workshop,
per-month plan/fact/expenses/payments grid. Reuses cockpit_service's own
revenue/payments computation (see that module's tests for the underlying
filtering rules in depth) - these tests focus on budget_service's own
responsibilities: the 12-month grid shape, manual-entry upsert, and that
fact_revenue/payments land in the right calendar month.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cost_expense import CostExpense
from app.models.cost_item import CostItem
from app.models.department import Department
from app.models.work_order import WorkOrder
from app.models.work_order_invoice import WorkOrderInvoice
from app.models.work_order_payment_event import WorkOrderPaymentEvent
from app.models.workshop import Workshop
from app.models.workshop_source_department import WorkshopSourceDepartment
from app.services import budget_service, cockpit_service

MECHANICAL_DEPT = "Слесарный цех_(ИП Пан)"
NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)


class _FakeSettings:
    revenue_statuses_list: list[str] = []


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch) -> None:
    monkeypatch.setattr(cockpit_service, "get_settings", lambda: _FakeSettings())


@pytest.fixture()
def department(db_session: Session) -> Department:
    dept = Department(name="Каховка")
    db_session.add(dept)
    db_session.commit()
    db_session.refresh(dept)
    return dept


@pytest.fixture()
def workshop(db_session: Session, department: Department) -> Workshop:
    ws = Workshop(
        department_id=department.id,
        workshop_type="Слесарный",
        posts_count=2,
        start_time="08:00:00",
        end_time="20:00:00",
        working_days=[0, 1, 2, 3, 4],
    )
    db_session.add(ws)
    db_session.flush()
    db_session.add(WorkshopSourceDepartment(workshop_id=ws.id, source_department=MECHANICAL_DEPT))
    db_session.commit()
    db_session.refresh(ws)
    return ws


def _work_order(**overrides) -> WorkOrder:
    defaults = dict(
        external_number=f"WO-{uuid.uuid4().hex[:8]}",
        source_system="alpha-auto",
        document_date=datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC),
        department=MECHANICAL_DEPT,
        amount=Decimal("1000.00"),
    )
    defaults.update(overrides)
    return WorkOrder(**defaults)


def test_budget_year_has_twelve_months_per_workshop(
    db_session: Session, workshop: Workshop
) -> None:
    rows = budget_service.get_budget_year(db_session, 2026, now=NOW)
    assert len(rows) == 1
    assert [m.month for m in rows[0].months] == list(range(1, 13))


def test_future_month_is_zero(db_session: Session, workshop: Workshop) -> None:
    rows = budget_service.get_budget_year(db_session, 2026, now=NOW)
    december = rows[0].months[11]
    assert december.fact_revenue == Decimal("0")
    assert december.payments == Decimal("0")


def test_fact_revenue_counts_closed_work_order_in_its_own_month(
    db_session: Session, workshop: Workshop
) -> None:
    db_session.add(
        _work_order(
            closed_date=datetime(2026, 9, 15, 10, 0, 0, tzinfo=UTC),
            amount=Decimal("5000"),
            repair_type="Текущий",
        )
    )
    db_session.commit()

    rows = budget_service.get_budget_year(db_session, 2026, now=NOW)
    september = rows[0].months[8]
    august = rows[0].months[7]
    assert september.fact_revenue == Decimal("5000")
    assert august.fact_revenue == Decimal("0")
    assert september.profit == Decimal("5000")  # no expenses entered yet


def test_payments_count_in_their_own_paid_month(db_session: Session, workshop: Workshop) -> None:
    wo = _work_order()
    db_session.add(wo)
    db_session.flush()
    db_session.add(
        WorkOrderPaymentEvent(
            work_order_id=wo.id,
            amount=Decimal("300"),
            paid_at=datetime(2026, 9, 10, tzinfo=UTC),
            source_document_id="pay-1",
        )
    )
    db_session.commit()

    rows = budget_service.get_budget_year(db_session, 2026, now=NOW)
    september = rows[0].months[8]
    assert september.payments == Decimal("300")
    assert september.money == Decimal("300")  # no expenses entered yet


def test_revenue_paid_counts_only_orders_behind_revenue(
    db_session: Session, workshop: Workshop
) -> None:
    closed = datetime(2026, 9, 15, 10, 0, 0, tzinfo=UTC)
    db_session.add_all(
        [
            _work_order(
                closed_date=closed,
                amount=Decimal("5000"),
                paid_amount=Decimal("3000"),
                repair_type="Текущий",
            ),
            # warranty is not revenue - its payment must not count either
            _work_order(
                closed_date=closed,
                amount=Decimal("700"),
                paid_amount=Decimal("700"),
                repair_type="Гарантийный",
            ),
            # not closed in September - no revenue, no "Оплачено"
            _work_order(amount=Decimal("900"), paid_amount=Decimal("900"), repair_type="Текущий"),
        ]
    )
    db_session.commit()

    september = budget_service.get_budget_year(db_session, 2026, now=NOW)[0].months[8]
    assert september.fact_revenue == Decimal("5000")
    assert september.revenue_paid == Decimal("3000")
    assert september.payments == Decimal("0")  # no payment events: a different measure


def test_revenue_unpaid_is_revenue_minus_paid_and_lists_underpaid_orders(
    db_session: Session, workshop: Workshop
) -> None:
    closed = datetime(2026, 9, 15, 10, 0, 0, tzinfo=UTC)
    partly = _work_order(
        closed_date=closed,
        amount=Decimal("5000"),
        paid_amount=Decimal("3000"),
        repair_type="Текущий",
    )
    unpaid = _work_order(closed_date=closed, amount=Decimal("2000"), repair_type="Текущий")
    full = _work_order(
        closed_date=closed,
        amount=Decimal("1000"),
        paid_amount=Decimal("1000"),
        repair_type="Текущий",
    )
    db_session.add_all([partly, unpaid, full])
    db_session.commit()

    september = budget_service.get_budget_year(db_session, 2026, now=NOW)[0].months[8]
    assert september.fact_revenue == Decimal("8000")
    assert september.revenue_paid == Decimal("4000")
    assert september.revenue_unpaid == Decimal("4000")  # 8000 - 4000

    def ids(kind: str) -> set:
        filters = budget_service.fact_order_filters(
            db_session, year=2026, month=9, kind=kind, workshop_id=workshop.id, now=NOW
        )
        return set(db_session.scalars(select(WorkOrder.id).where(*filters)))

    assert ids("unpaid") == {partly.id, unpaid.id}
    assert ids("all") == {partly.id, unpaid.id, full.id}


def test_fact_order_filters_cover_a_period_of_several_months(
    db_session: Session, workshop: Workshop
) -> None:
    july = _work_order(
        closed_date=datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC),
        amount=Decimal("100"),
        repair_type="Текущий",
    )
    aug = _work_order(
        closed_date=datetime(2026, 8, 10, 10, 0, 0, tzinfo=UTC),
        amount=Decimal("200"),
        repair_type="Текущий",
    )
    sep = _work_order(
        closed_date=datetime(2026, 9, 5, 10, 0, 0, tzinfo=UTC),
        amount=Decimal("400"),
        repair_type="Текущий",
    )
    db_session.add_all([july, aug, sep])
    db_session.commit()

    def ids(**kw) -> set:
        filters = budget_service.fact_order_filters(
            db_session, kind="main", workshop_id=workshop.id, now=NOW, **kw
        )
        return set(db_session.scalars(select(WorkOrder.id).where(*filters)))

    assert ids(year=2026, month=8) == {aug.id}
    # Столбец ИТОГО: август-сентябрь - ровно заказ-наряды, из которых сложилась сумма периода
    assert ids(year=2026, month=8, year_to=2026, month_to=9) == {aug.id, sep.id}
    assert ids(year=2026, month=7, year_to=2026, month_to=9) == {july.id, aug.id, sep.id}


def test_unpaid_is_split_into_overdue_and_not_due(db_session: Session, workshop: Workshop) -> None:
    # NOW = 28.09.2026. Физлицо - просрочено со следующего дня после закрытия; юрлицо - через
    # 21 день от даты счёта (нет счёта - от даты закрытия).
    def order(closed_day: int, customer: str, **kw) -> WorkOrder:
        return _work_order(
            closed_date=datetime(2026, 9, closed_day, 10, 0, 0, tzinfo=UTC),
            amount=Decimal("1000"),
            repair_type="Текущий",
            customer_name=customer,
            **kw,
        )

    person = "Иванов Иван Иванович"
    company = 'ООО "Ромашка"'
    person_overdue = order(27, person)  # закрыт вчера
    person_today = order(28, person)  # закрыт сегодня - ещё не просрочен
    company_overdue = order(5, company)  # 23 дня без счёта
    company_fresh = order(10, company)  # 18 дней без счёта
    company_invoiced = order(1, company)  # закрыт давно, но счёт выставлен 15.09 - 13 дней
    company_old_invoice = order(25, company)  # счёт от 01.09 - 27 дней
    paid = order(1, company, paid_amount=Decimal("1500"))  # оплачен с переплатой - не в долгах
    partly = order(2, person, paid_amount=Decimal("400"))  # долг 600, просрочен
    db_session.add_all(
        [
            person_overdue,
            person_today,
            company_overdue,
            company_fresh,
            company_invoiced,
            company_old_invoice,
            paid,
            partly,
        ]
    )
    db_session.flush()
    for wo, day in ((company_invoiced, 15), (company_old_invoice, 1)):
        db_session.add(
            WorkOrderInvoice(
                work_order_id=wo.id,
                source_document_id=f"inv-{wo.id}",
                document_date=datetime(2026, 9, day, 9, 0, 0, tzinfo=UTC),
                amount=Decimal("1000"),
            )
        )
    db_session.commit()

    september = budget_service.get_budget_year(db_session, 2026, now=NOW)[0].months[8]
    assert september.revenue_unpaid == Decimal("6600")  # 7 x 1000 - 400
    assert september.revenue_overdue == Decimal("3600")  # 1000 + 1000 + 1000 + 600
    assert september.revenue_not_due == Decimal("3000")
    assert september.revenue_overdue + september.revenue_not_due == september.revenue_unpaid

    def ids(kind: str) -> set:
        filters = budget_service.fact_order_filters(
            db_session, year=2026, month=9, kind=kind, workshop_id=workshop.id, now=NOW
        )
        return set(db_session.scalars(select(WorkOrder.id).where(*filters)))

    assert ids("overdue") == {
        person_overdue.id,
        company_overdue.id,
        company_old_invoice.id,
        partly.id,
    }
    assert ids("not_due") == {person_today.id, company_fresh.id, company_invoiced.id}


def test_set_budget_value_upserts_plan_revenue(db_session: Session, workshop: Workshop) -> None:
    budget_service.set_budget_value(
        db_session,
        workshop_id=workshop.id,
        year=2026,
        month=9,
        field="plan_revenue",
        value=Decimal("100000"),
    )
    rows = budget_service.get_budget_year(db_session, 2026, now=NOW)
    assert rows[0].months[8].plan_revenue == Decimal("100000")

    # A second write to the same cell updates in place, not a duplicate row.
    budget_service.set_budget_value(
        db_session,
        workshop_id=workshop.id,
        year=2026,
        month=9,
        field="plan_revenue",
        value=Decimal("200000"),
    )
    rows = budget_service.get_budget_year(db_session, 2026, now=NOW)
    assert rows[0].months[8].plan_revenue == Decimal("200000")


def test_expenses_are_the_sum_of_cost_items_and_feed_profit_and_money(
    db_session: Session, workshop: Workshop
) -> None:
    db_session.add(
        _work_order(
            closed_date=datetime(2026, 9, 15, tzinfo=UTC),
            amount=Decimal("5000"),
            repair_type="Текущий",
        )
    )
    rent = CostItem(name="Аренда", is_active=True)
    wages = CostItem(name="Зарплата", is_active=False)  # inactive still counts
    db_session.add_all([rent, wages])
    db_session.flush()
    for item, amount in ((rent, "1000"), (wages, "200")):
        db_session.add(
            CostExpense(
                cost_item_id=item.id,
                workshop_id=workshop.id,
                year=2026,
                month=9,
                amount=Decimal(amount),
            )
        )
    db_session.commit()

    rows = budget_service.get_budget_year(db_session, 2026, now=NOW)
    september = rows[0].months[8]
    assert september.expenses == Decimal("1200")
    assert september.profit == Decimal("3800")
    # Денежная прибыль = чистая - «Без оплат» (ничего не оплачено - весь долг вычитается)
    assert september.cash_profit == september.profit - september.revenue_unpaid
    assert september.money == Decimal("-1200")  # no payments this month


def test_manual_expenses_in_the_budget_are_refused(db_session: Session, workshop: Workshop) -> None:
    with pytest.raises(ValueError, match="статьям затрат"):
        budget_service.set_budget_value(
            db_session,
            workshop_id=workshop.id,
            year=2026,
            month=9,
            field="expenses",
            value=Decimal("1200"),
        )


def test_fact_revenue_is_two_rows_insurance_and_current_only(
    db_session: Session, workshop: Workshop
) -> None:
    """Страховые by the configured insurance repair type, основные by
    "Текущий"; every other type (Основной, Гарантийный, Виртуальный, none)
    generates no revenue here; internal orders are skipped when the setting
    says so."""
    from app.services.settings_service import get_app_settings

    app_settings = get_app_settings(db_session)
    app_settings.insurance_repair_type = "Страховой"
    app_settings.order_exclusion_mode = "internal"
    app_settings.warranty_repair_types = ["Гарантийный"]
    app_settings.virtual_repair_types = ["Виртуальный"]
    closed = datetime(2026, 9, 15, tzinfo=UTC)
    db_session.add_all(
        [
            _work_order(closed_date=closed, amount=Decimal("100"), repair_type="Страховой"),
            _work_order(closed_date=closed, amount=Decimal("1000"), repair_type="Текущий"),
            _work_order(closed_date=closed, amount=Decimal("20"), repair_type="Текущий"),
            _work_order(
                closed_date=closed, amount=Decimal("7"), repair_type="Текущий", is_internal=True
            ),
            _work_order(closed_date=closed, amount=Decimal("5"), repair_type="Основной"),
            _work_order(closed_date=closed, amount=Decimal("9000"), repair_type="Гарантийный"),
            _work_order(closed_date=closed, amount=Decimal("8000"), repair_type="Виртуальный"),
            _work_order(closed_date=closed, amount=Decimal("3"), repair_type=None),
        ]
    )
    db_session.commit()

    rows = budget_service.get_budget_year(db_session, 2026, now=NOW)
    september = rows[0].months[8]
    assert september.fact_revenue_insurance == Decimal("100")
    assert september.fact_revenue_main == Decimal("1020")
    assert september.fact_revenue == Decimal("1120")


def test_the_orders_behind_a_fact_revenue_cell_add_up_to_the_cell(
    db_session: Session, workshop: Workshop
) -> None:
    """Клик по ячейке «Выручка факт ...» открывает список ЗН: те же фильтры, та же сумма."""
    from app.services.settings_service import get_app_settings

    get_app_settings(db_session).insurance_repair_type = "Страховой"
    other_dept = Department(name="Другой")
    db_session.add(other_dept)
    db_session.flush()
    other = Workshop(
        department_id=other_dept.id,
        workshop_type="Кузовной",
        posts_count=1,
        start_time="08:00:00",
        end_time="20:00:00",
        working_days=[0, 1, 2, 3, 4],
    )
    db_session.add(other)
    db_session.flush()
    db_session.add(WorkshopSourceDepartment(workshop_id=other.id, source_department="Кузов"))
    closed = datetime(2026, 9, 15, tzinfo=UTC)
    db_session.add_all(
        [
            _work_order(closed_date=closed, amount=Decimal("100"), repair_type="Страховой"),
            _work_order(closed_date=closed, amount=Decimal("1000"), repair_type="Текущий"),
            _work_order(closed_date=closed, amount=Decimal("5"), repair_type="Основной"),
            _work_order(  # другой месяц
                closed_date=datetime(2026, 8, 15, tzinfo=UTC),
                amount=Decimal("7"),
                repair_type="Текущий",
            ),
            _work_order(
                closed_date=closed, amount=Decimal("40"), repair_type="Текущий", department="Кузов"
            ),
        ]
    )
    db_session.commit()

    def amounts(kind, workshop_id=None):
        filters = budget_service.fact_order_filters(
            db_session, year=2026, month=9, kind=kind, workshop_id=workshop_id, now=NOW
        )
        orders = db_session.scalars(select(WorkOrder).where(*filters)).all()
        return sorted(order.amount for order in orders)

    rows = budget_service.get_budget_year(db_session, 2026, now=NOW)
    cell = next(r for r in rows if r.workshop_id == workshop.id).months[8]
    assert sum(amounts("main", workshop.id)) == cell.fact_revenue_main == Decimal("1000")
    assert sum(amounts("insurance", workshop.id)) == cell.fact_revenue_insurance
    assert amounts("main") == [Decimal("40"), Decimal("1000")]  # вся компания: оба цеха
    assert amounts("insurance") == [Decimal("100")]


def test_allocate_external_splits_insurance_revenue_between_the_internal_orders_workshops(
    db_session: Session, workshop: Workshop
) -> None:
    """«Аллоцировать внешние»: выручка страхового ЗН делится между цехами внутренних ЗН той же
    машины пропорционально их суммам; итог по компании не меняется; список ЗН цеха согласован."""
    from app.services.settings_service import get_app_settings

    app_settings = get_app_settings(db_session)
    app_settings.insurance_repair_type = "Страховой"
    body_dept = Department(name="Кузов-отдел")
    db_session.add(body_dept)
    db_session.flush()
    body = Workshop(
        department_id=body_dept.id,
        workshop_type="Кузовной",
        posts_count=1,
        start_time="08:00:00",
        end_time="20:00:00",
        working_days=[0, 1, 2, 3, 4],
    )
    db_session.add(body)
    db_session.flush()
    db_session.add(WorkshopSourceDepartment(workshop_id=body.id, source_department="Кузов"))
    closed = datetime(2026, 9, 15, tzinfo=UTC)
    vin = "WAUZZZ4M9MD015350"
    insurance = _work_order(
        department="Кузов",
        closed_date=closed,
        amount=Decimal("10000"),
        paid_amount=Decimal("4000"),
        repair_type="Страховой",
        car_key=vin,
    )
    alone = _work_order(  # внутренние ЗН только в одном цехе - остаётся как есть
        department="Кузов",
        closed_date=closed,
        amount=Decimal("500"),
        repair_type="Страховой",
        car_key="XTAGFK440MY559444",
    )
    db_session.add_all(
        [
            insurance,
            alone,
            _work_order(
                amount=Decimal("1000"), repair_type="Текущий", car_key=vin, is_internal=True
            ),
            _work_order(  # отказ - вес не имеет, как будто его нет
                department="Кузов",
                amount=Decimal("50000"),
                repair_type="Текущий",
                car_key=vin,
                is_internal=True,
                status="Отказ",
            ),
            _work_order(
                department="Кузов",
                amount=Decimal("3000"),
                repair_type="Текущий",
                car_key=vin,
                is_internal=True,
            ),
            _work_order(
                department="Кузов",
                amount=Decimal("700"),
                repair_type="Текущий",
                car_key="XTAGFK440MY559444",
                is_internal=True,
            ),
        ]
    )
    db_session.commit()

    def september(workshop_id):
        rows = budget_service.get_budget_year(db_session, 2026, now=NOW)
        return next(r for r in rows if r.workshop_id == workshop_id).months[8]

    # Выключено: всё в цехе самого ЗН
    assert september(body.id).fact_revenue_insurance == Decimal("10500")
    assert september(workshop.id).fact_revenue_insurance == Decimal("0")

    app_settings.allocate_external = True
    db_session.commit()
    mech, kuzov = september(workshop.id), september(body.id)
    assert mech.fact_revenue_insurance == Decimal("2500.00")  # 1000 / 4000 от 10 000
    assert kuzov.fact_revenue_insurance == Decimal("8000.00")  # 7500 + 500 остаётся
    assert mech.revenue_paid == Decimal("1000.00")
    assert kuzov.revenue_paid == Decimal("3000.00")
    assert mech.revenue_unpaid + kuzov.revenue_unpaid == Decimal("6500")  # 6000 + 500
    assert mech.fact_revenue + kuzov.fact_revenue == Decimal("10500")  # итог не меняется

    def order_ids(workshop_id):
        filters = budget_service.fact_order_filters(
            db_session, year=2026, month=9, kind="insurance", workshop_id=workshop_id, now=NOW
        )
        return set(db_session.scalars(select(WorkOrder.id).where(*filters)))

    assert order_ids(workshop.id) == {insurance.id}
    assert order_ids(body.id) == {insurance.id, alone.id}
    assert order_ids(None) == {insurance.id, alone.id}


def test_set_budget_value_rejects_unknown_field(db_session: Session, workshop: Workshop) -> None:
    with pytest.raises(ValueError):
        budget_service.set_budget_value(
            db_session,
            workshop_id=workshop.id,
            year=2026,
            month=9,
            field="bogus",
            value=Decimal("1"),
        )


def test_fact_revenue_sub_rows_are_the_labor_and_part_lines_of_the_same_orders(
    db_session: Session, workshop: Workshop
) -> None:
    """Работы / Запчасти under each fact row: the sums of the labor and part
    lines of exactly the orders that make up that row."""
    from app.models.work_order_line import WorkOrderLaborLine, WorkOrderPartLine
    from app.services.settings_service import get_app_settings

    get_app_settings(db_session).insurance_repair_type = "Страховой"
    closed = datetime(2026, 9, 15, tzinfo=UTC)
    insurance = _work_order(closed_date=closed, amount=Decimal("1000"), repair_type="Страховой")
    main = _work_order(closed_date=closed, amount=Decimal("500"), repair_type="Текущий")
    other = _work_order(closed_date=closed, amount=Decimal("9999"), repair_type="Основной")
    old = _work_order(
        closed_date=datetime(2026, 8, 15, tzinfo=UTC), amount=Decimal("77"), repair_type="Текущий"
    )
    db_session.add_all([insurance, main, other, old])
    db_session.flush()
    for order, labor, parts in (
        (insurance, "300", "700"),
        (main, "200", "300"),
        (other, "5000", "4999"),  # not a revenue row: stays out
        (old, "70", "7"),  # another month: stays out
    ):
        db_session.add(WorkOrderLaborLine(work_order_id=order.id, amount=Decimal(labor)))
        db_session.add(WorkOrderPartLine(work_order_id=order.id, amount=Decimal(parts)))
    db_session.commit()

    september = budget_service.get_budget_year(db_session, 2026, now=NOW)[0].months[8]

    assert september.fact_revenue_insurance == Decimal("1000")
    assert september.fact_revenue_insurance_labor == Decimal("300")
    assert september.fact_revenue_insurance_parts == Decimal("700")
    assert september.fact_revenue_main == Decimal("500")
    assert september.fact_revenue_main_labor == Decimal("200")
    assert september.fact_revenue_main_parts == Decimal("300")
    # the sub-rows add up to the row above
    assert september.fact_revenue_main == september.fact_revenue_main_labor + (
        september.fact_revenue_main_parts
    )


def test_fact_revenue_sub_rows_use_the_line_total_after_the_discount(
    db_session: Session, workshop: Workshop
) -> None:
    """Работы = 470 300 before a 5% discount, 446 785 after it: the sub-row takes
    the AFTER amount so Работы + Запчасти = the document amount; lines imported
    before the discount was exported (no total) fall back to their amount."""
    from app.models.work_order_line import WorkOrderLaborLine, WorkOrderPartLine

    order = _work_order(
        closed_date=datetime(2026, 9, 15, tzinfo=UTC),
        amount=Decimal("763885"),
        repair_type="Текущий",
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(
        WorkOrderLaborLine(
            work_order_id=order.id,
            amount=Decimal("470300"),
            discount_amount=Decimal("23515"),
            total_amount=Decimal("446785"),
        )
    )
    db_session.add(WorkOrderPartLine(work_order_id=order.id, amount=Decimal("317100")))  # old row
    db_session.commit()

    september = budget_service.get_budget_year(db_session, 2026, now=NOW)[0].months[8]

    assert september.fact_revenue_main == Decimal("763885")
    assert september.fact_revenue_main_labor == Decimal("446785")
    assert september.fact_revenue_main_parts == Decimal("317100")
    assert (
        september.fact_revenue_main_labor + september.fact_revenue_main_parts
        == september.fact_revenue_main
    )
