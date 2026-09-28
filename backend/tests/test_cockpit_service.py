"""Tests for services/cockpit_service.py - the Cockpit landing page's
revenue/payments/НЗП calculations and the adaptive gauge-scale algorithm.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.body_car import BodyCar
from app.models.body_car_stage import BodyCarStage
from app.models.department import Department
from app.models.work_order import WorkOrder
from app.models.work_order_payment_event import WorkOrderPaymentEvent
from app.models.workshop import Workshop
from app.models.workshop_source_department import WorkshopSourceDepartment
from app.services import cockpit_service

# Mid-month "now" - MSK is UTC+3, so this is 2026-09-28 15:00 MSK: period
# start is 2026-09-01 00:00 MSK (2026-08-31 21:00 UTC), period end is `NOW`
# itself.
NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)
PERIOD_START = datetime(2026, 8, 31, 21, 0, 0, tzinfo=UTC)

MECHANICAL_DEPT = "Слесарный цех_(ИП Пан)"
BODY_DEPT = "Кузовной цех (Каховка)"


def _make_work_order(**overrides) -> WorkOrder:
    defaults = dict(
        external_number=f"WO-{uuid.uuid4().hex[:8]}",
        source_system="alpha-auto",
        document_date=datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC),
        amount=Decimal("1000.00"),
    )
    defaults.update(overrides)
    return WorkOrder(**defaults)


class _FakeSettings:
    def __init__(self, revenue_statuses: list[str] | None = None) -> None:
        self.revenue_statuses_list = revenue_statuses or []


def _patch_settings(monkeypatch, revenue_statuses: list[str] | None = None) -> None:
    monkeypatch.setattr(cockpit_service, "get_settings", lambda: _FakeSettings(revenue_statuses))


# ---- compute_gauge_scale (pure function) -----------------------------------


@pytest.mark.parametrize(
    ("plan_millions", "expected_step", "expected_max"),
    [
        (Decimal(10), 2, 14),
        (Decimal(16), 2, 20),
        (Decimal(50), 10, 70),
        (Decimal(13), 2, 18),
        # A small plan would otherwise collapse to just 2-3 tick intervals
        # (the bare "+2" headroom) - MIN_SCALE_INTERVALS floors the total
        # at 6, so this is 1/6 here, not the original spec's 1/3.
        (Decimal("0.5"), 1, 6),
    ],
)
def test_compute_gauge_scale_worked_examples(plan_millions, expected_step, expected_max) -> None:
    scale = cockpit_service.compute_gauge_scale(plan_millions * Decimal(1_000_000))

    assert scale.step_millions == expected_step
    assert scale.max_millions == expected_max
    assert scale.labels_millions == list(range(0, expected_max + 1, expected_step))
    assert scale.marker_fraction == pytest.approx(float(plan_millions) / expected_max)


def test_compute_gauge_scale_labels_are_integers_only() -> None:
    scale = cockpit_service.compute_gauge_scale(Decimal(13_000_000))
    assert all(isinstance(label, int) for label in scale.labels_millions)


# ---- period_bounds -----------------------------------------------------


def test_period_bounds_is_msk_month_start_to_now() -> None:
    start, end = cockpit_service.period_bounds(NOW)
    assert start == PERIOD_START
    assert end == NOW


# ---- fixtures: department/workshop + the 1C-string mapping ----------------


@pytest.fixture()
def department(db_session: Session) -> Department:
    dept = Department(name="Каховка")
    db_session.add(dept)
    db_session.commit()
    db_session.refresh(dept)
    return dept


@pytest.fixture()
def mechanical_workshop(db_session: Session, department: Department) -> Workshop:
    workshop = Workshop(
        department_id=department.id,
        workshop_type="Слесарный",
        posts_count=2,
        start_time="08:00:00",
        end_time="20:00:00",
        working_days=[0, 1, 2, 3, 4],
    )
    db_session.add(workshop)
    db_session.flush()
    db_session.add(
        WorkshopSourceDepartment(workshop_id=workshop.id, source_department=MECHANICAL_DEPT)
    )
    db_session.commit()
    db_session.refresh(workshop)
    return workshop


@pytest.fixture()
def body_workshop(db_session: Session, department: Department) -> Workshop:
    workshop = Workshop(
        department_id=department.id,
        workshop_type="Кузовной",
        posts_count=1,
        start_time="08:00:00",
        end_time="20:00:00",
        working_days=[0, 1, 2, 3, 4],
    )
    db_session.add(workshop)
    db_session.flush()
    db_session.add(WorkshopSourceDepartment(workshop_id=workshop.id, source_department=BODY_DEPT))
    db_session.commit()
    db_session.refresh(workshop)
    return workshop


# ---- get_snapshot: revenue ----------------------------------------------


def test_revenue_counts_only_closed_in_period(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    db_session.add_all(
        [
            _make_work_order(
                closed_date=datetime(2026, 9, 15, tzinfo=UTC), amount=Decimal("1000.00")
            ),
            _make_work_order(
                closed_date=datetime(2026, 8, 15, tzinfo=UTC), amount=Decimal("500.00")
            ),  # too early
            _make_work_order(closed_date=None, amount=Decimal("999.00")),  # not closed
        ]
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=None, include_nzp=False, now=NOW
    )

    assert snapshot.revenue_rub == Decimal("1000.00")


def test_revenue_scoped_to_workshop_via_mapping(
    db_session: Session, mechanical_workshop: Workshop, monkeypatch
) -> None:
    _patch_settings(monkeypatch)
    db_session.add_all(
        [
            _make_work_order(
                department=MECHANICAL_DEPT,
                closed_date=datetime(2026, 9, 10, tzinfo=UTC),
                amount=Decimal("300.00"),
            ),
            _make_work_order(
                department="Кузовной цех_Солнцево",
                closed_date=datetime(2026, 9, 10, tzinfo=UTC),
                amount=Decimal("700.00"),
            ),
        ]
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=mechanical_workshop.id, include_nzp=False, now=NOW
    )

    assert snapshot.revenue_rub == Decimal("300.00")
    assert snapshot.workshop_label == "Каховка — Слесарный"


def test_revenue_scoped_to_workshop_with_no_mapping_is_zero(
    db_session: Session, department: Department, monkeypatch
) -> None:
    _patch_settings(monkeypatch)
    unmapped_workshop = Workshop(
        department_id=department.id,
        workshop_type="Слесарный",
        posts_count=1,
        start_time="08:00:00",
        end_time="20:00:00",
        working_days=[0, 1, 2, 3, 4],
    )
    db_session.add(unmapped_workshop)
    db_session.flush()
    db_session.add(
        _make_work_order(
            department="Что-то ещё",
            closed_date=datetime(2026, 9, 10, tzinfo=UTC),
            amount=Decimal("999.00"),
        )
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=unmapped_workshop.id, include_nzp=False, now=NOW
    )

    assert snapshot.revenue_rub == Decimal("0")


def test_revenue_respects_configured_revenue_status(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch, revenue_statuses=["Закрыт"])
    db_session.add_all(
        [
            _make_work_order(
                status="Закрыт",
                closed_date=datetime(2026, 9, 10, tzinfo=UTC),
                amount=Decimal("100.00"),
            ),
            _make_work_order(
                status="Заявка",
                closed_date=datetime(2026, 9, 10, tzinfo=UTC),
                amount=Decimal("900.00"),
            ),
        ]
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=None, include_nzp=False, now=NOW
    )

    assert snapshot.revenue_rub == Decimal("100.00")


def test_unattributed_revenue_flagged_company_wide_only(
    db_session: Session, mechanical_workshop: Workshop, monkeypatch
) -> None:
    _patch_settings(monkeypatch)
    db_session.add(
        _make_work_order(
            department="Неизвестная строка 1С", closed_date=datetime(2026, 9, 10, tzinfo=UTC)
        )
    )
    db_session.commit()

    company_wide = cockpit_service.get_snapshot(
        db_session, workshop_id=None, include_nzp=False, now=NOW
    )
    scoped = cockpit_service.get_snapshot(
        db_session, workshop_id=mechanical_workshop.id, include_nzp=False, now=NOW
    )

    assert company_wide.has_unattributed_revenue is True
    # Unattributed revenue still counts toward the company-wide total.
    assert company_wide.revenue_rub == Decimal("1000.00")
    assert scoped.has_unattributed_revenue is False


# ---- get_snapshot: payments ----------------------------------------------


def test_payments_counts_by_paid_at_not_document_date(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    wo = _make_work_order(
        document_date=datetime(2026, 6, 1, tzinfo=UTC), amount=Decimal("50000.00")
    )
    db_session.add(wo)
    db_session.flush()
    db_session.add_all(
        [
            WorkOrderPaymentEvent(
                work_order_id=wo.id,
                paid_at=datetime(2026, 9, 20, tzinfo=UTC),
                amount=Decimal("30000.00"),
                source_document_id="pay-1",
            ),
            WorkOrderPaymentEvent(
                work_order_id=wo.id,
                paid_at=datetime(2026, 8, 20, tzinfo=UTC),
                amount=Decimal("20000.00"),
                source_document_id="pay-2",
            ),  # earlier month - excluded
        ]
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=None, include_nzp=False, now=NOW
    )

    assert snapshot.payments_rub == Decimal("30000.00")


def test_payments_scoped_to_workshop_via_mapping(
    db_session: Session, mechanical_workshop: Workshop, monkeypatch
) -> None:
    _patch_settings(monkeypatch)
    wo_in = _make_work_order(department=MECHANICAL_DEPT)
    wo_out = _make_work_order(department="Кузовной цех_Солнцево")
    db_session.add_all([wo_in, wo_out])
    db_session.flush()
    paid_at = datetime(2026, 9, 28, 9, 0, 0, tzinfo=UTC)  # inside the period (before NOW)
    db_session.add_all(
        [
            WorkOrderPaymentEvent(
                work_order_id=wo_in.id,
                paid_at=paid_at,
                amount=Decimal("111.00"),
                source_document_id="pay-in",
            ),
            WorkOrderPaymentEvent(
                work_order_id=wo_out.id,
                paid_at=paid_at,
                amount=Decimal("222.00"),
                source_document_id="pay-out",
            ),
        ]
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=mechanical_workshop.id, include_nzp=False, now=NOW
    )

    assert snapshot.payments_rub == Decimal("111.00")


# ---- get_snapshot: НЗП ----------------------------------------------------


def test_nzp_is_always_zero_for_a_mechanical_workshop_scope(
    db_session: Session, mechanical_workshop: Workshop, monkeypatch
) -> None:
    """Confirmed product decision: Слесарный has no НЗП concept at all -
    an open order with a near-term planned end_date must not contribute,
    unlike the old (now-removed) Слесарный end_date rule would have."""
    _patch_settings(monkeypatch)
    db_session.add(
        _make_work_order(
            department=MECHANICAL_DEPT,
            closed_date=None,
            end_date=datetime(2026, 9, 27, tzinfo=UTC),
            amount=Decimal("400.00"),
        )
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=mechanical_workshop.id, include_nzp=True, now=NOW
    )

    assert snapshot.nzp_rub == Decimal("0")


def test_nzp_company_wide_ignores_mechanical_and_only_sums_body(
    db_session: Session, mechanical_workshop: Workshop, body_workshop: Workshop, monkeypatch
) -> None:
    """Company-wide НЗП must not pick up a Слесарный workshop's open orders
    even though they're in scope - only Кузовной ever contributes, and its
    real contribution still comes through correctly alongside that."""
    _patch_settings(monkeypatch)
    db_session.add(
        _make_work_order(
            department=MECHANICAL_DEPT,
            closed_date=None,
            end_date=datetime(2026, 9, 27, tzinfo=UTC),
            amount=Decimal("400.00"),
        )
    )
    wo = _make_work_order(department=BODY_DEPT, closed_date=None, amount=Decimal("777.00"))
    db_session.add(wo)
    db_session.flush()
    car = BodyCar(workshop_id=body_workshop.id, work_order_id=wo.id, color="#93c5fd")
    db_session.add(car)
    db_session.flush()
    db_session.add(
        BodyCarStage(
            body_car_id=car.id,
            stage_name="Выдача",
            start_date=date(2026, 9, 26),
            end_date=date(2026, 9, 27),
            sort_order=1,
        )
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(db_session, workshop_id=None, include_nzp=True, now=NOW)

    # 777.00 from the Кузовной car, nothing from the Слесарный order.
    assert snapshot.nzp_rub == Decimal("777.00")


def test_nzp_body_counts_once_for_two_qualifying_stages(
    db_session: Session, body_workshop: Workshop, monkeypatch
) -> None:
    _patch_settings(monkeypatch)
    wo = _make_work_order(department=BODY_DEPT, closed_date=None, amount=Decimal("777.00"))
    db_session.add(wo)
    db_session.flush()

    car = BodyCar(workshop_id=body_workshop.id, work_order_id=wo.id, color="#93c5fd")
    db_session.add(car)
    db_session.flush()
    db_session.add_all(
        [
            BodyCarStage(
                body_car_id=car.id,
                stage_name="Сборка-Полировка",
                start_date=date(2026, 9, 20),
                end_date=date(2026, 9, 25),
                sort_order=1,
            ),
            BodyCarStage(
                body_car_id=car.id,
                stage_name="Выдача",
                start_date=date(2026, 9, 26),
                end_date=date(2026, 9, 27),
                sort_order=2,
            ),
        ]
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=body_workshop.id, include_nzp=True, now=NOW
    )

    assert snapshot.nzp_rub == Decimal("777.00")


def test_nzp_body_stage_past_period_end_not_counted(
    db_session: Session, body_workshop: Workshop, monkeypatch
) -> None:
    _patch_settings(monkeypatch)
    wo = _make_work_order(department=BODY_DEPT, closed_date=None, amount=Decimal("777.00"))
    db_session.add(wo)
    db_session.flush()

    car = BodyCar(workshop_id=body_workshop.id, work_order_id=wo.id, color="#93c5fd")
    db_session.add(car)
    db_session.flush()
    db_session.add(
        BodyCarStage(
            body_car_id=car.id,
            stage_name="Выдача",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 3),  # after period end (28.09)
            sort_order=1,
        )
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=body_workshop.id, include_nzp=True, now=NOW
    )

    assert snapshot.nzp_rub == Decimal("0")


def test_nzp_omitted_when_not_requested(
    db_session: Session, mechanical_workshop: Workshop, monkeypatch
) -> None:
    _patch_settings(monkeypatch)
    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=mechanical_workshop.id, include_nzp=False, now=NOW
    )
    assert snapshot.nzp_rub is None
    assert snapshot.effective_revenue_rub == snapshot.revenue_rub


# ---- get_snapshot: plan / gauge ------------------------------------------


def test_plan_incomplete_when_one_workshop_missing_target(
    db_session: Session, department: Department, monkeypatch
) -> None:
    _patch_settings(monkeypatch)
    db_session.add_all(
        [
            Workshop(
                department_id=department.id,
                workshop_type="Слесарный",
                posts_count=2,
                start_time="08:00:00",
                end_time="20:00:00",
                working_days=[0, 1, 2, 3, 4],
                target_revenue=Decimal("10000000.00"),
            ),
            Workshop(
                department_id=department.id,
                workshop_type="Кузовной",
                posts_count=1,
                start_time="08:00:00",
                end_time="20:00:00",
                working_days=[0, 1, 2, 3, 4],
                target_revenue=None,
            ),
        ]
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=None, include_nzp=False, now=NOW
    )

    assert snapshot.plan.complete is False
    assert snapshot.plan.usable is False
    # No usable plan - the gauge still gets a real (neutral) scale derived
    # from the amounts themselves, not a null one, so the dial still shows
    # ticks/numbers instead of an empty face. No work orders exist in this
    # test, so both revenue and payments are 0 and the fallback anchors on
    # the hardcoded 1,000,000 floor - see get_snapshot().
    assert snapshot.revenue_gauge.scale is not None
    assert snapshot.revenue_gauge.scale.step_millions == 1
    # MIN_SCALE_INTERVALS floors this at 6 intervals, not the bare "+2"
    # headroom's 3.
    assert snapshot.revenue_gauge.scale.max_millions == 6
    assert snapshot.revenue_gauge.needle_fraction == 0.0


def test_plan_is_single_workshops_own_target(
    db_session: Session, mechanical_workshop: Workshop, monkeypatch
) -> None:
    _patch_settings(monkeypatch)
    mechanical_workshop.target_revenue = Decimal("6000000.00")
    db_session.add(
        _make_work_order(
            department=MECHANICAL_DEPT,
            closed_date=datetime(2026, 9, 10, tzinfo=UTC),
            amount=Decimal("3000000.00"),
        )
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=mechanical_workshop.id, include_nzp=False, now=NOW
    )

    assert snapshot.plan.total_rub == Decimal("6000000.00")
    assert snapshot.plan.workshop_count == 1
    assert snapshot.revenue_gauge.scale.step_millions == 1
    assert snapshot.revenue_gauge.scale.max_millions == 8
    assert snapshot.revenue_gauge.needle_fraction == pytest.approx(3.0 / 8.0)


def test_plan_sums_across_workshops_for_company_wide(
    db_session: Session, mechanical_workshop: Workshop, body_workshop: Workshop, monkeypatch
) -> None:
    _patch_settings(monkeypatch)
    mechanical_workshop.target_revenue = Decimal("6000000.00")
    body_workshop.target_revenue = Decimal("4000000.00")
    db_session.add(
        _make_work_order(
            department=MECHANICAL_DEPT,
            closed_date=datetime(2026, 9, 10, tzinfo=UTC),
            amount=Decimal("5000000.00"),
        )
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=None, include_nzp=False, now=NOW
    )

    assert snapshot.plan.total_rub == Decimal("10000000.00")
    assert snapshot.plan.usable is True
    assert snapshot.revenue_gauge.scale.step_millions == 2
    assert snapshot.revenue_gauge.scale.max_millions == 14
    assert snapshot.revenue_gauge.needle_fraction == pytest.approx(5.0 / 14.0)
    assert snapshot.revenue_gauge.overflow is False


def test_revenue_overflow_clamps_needle_and_flags(
    db_session: Session, mechanical_workshop: Workshop, monkeypatch
) -> None:
    _patch_settings(monkeypatch)
    mechanical_workshop.target_revenue = Decimal("1000000.00")
    db_session.add(
        _make_work_order(
            department=MECHANICAL_DEPT,
            closed_date=datetime(2026, 9, 10, tzinfo=UTC),
            amount=Decimal("50000000.00"),
        )
    )
    db_session.commit()

    snapshot = cockpit_service.get_snapshot(
        db_session, workshop_id=mechanical_workshop.id, include_nzp=False, now=NOW
    )

    assert snapshot.revenue_gauge.overflow is True
    assert snapshot.revenue_gauge.needle_fraction == 1.0
    # The exact amount is still reported in full, unrounded - only the
    # needle/scale are clamped, per the product spec.
    assert snapshot.revenue_rub == Decimal("50000000.00")
