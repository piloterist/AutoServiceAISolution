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
from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.work_order import WorkOrder
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
        _work_order(closed_date=datetime(2026, 9, 15, 10, 0, 0, tzinfo=UTC), amount=Decimal("5000"))
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


def test_set_budget_value_expenses_feed_profit_and_money(
    db_session: Session, workshop: Workshop
) -> None:
    db_session.add(
        _work_order(closed_date=datetime(2026, 9, 15, tzinfo=UTC), amount=Decimal("5000"))
    )
    db_session.commit()
    budget_service.set_budget_value(
        db_session,
        workshop_id=workshop.id,
        year=2026,
        month=9,
        field="expenses",
        value=Decimal("1200"),
    )

    rows = budget_service.get_budget_year(db_session, 2026, now=NOW)
    september = rows[0].months[8]
    assert september.expenses == Decimal("1200")
    assert september.profit == Decimal("3800")
    assert september.money == Decimal("-1200")  # no payments this month


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
