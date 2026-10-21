"""Tests for services/receivables_service.py - the Финансы -> Дебиторская
задолженность aging report. The "what counts as ДЗ" filter is the same one
cockpit_service._receivables already has thorough coverage for (see
test_cockpit_service.py's "get_snapshot: receivables_rub" section) - these
tests focus on what's new here: the per-row aging bucket and the invoice-date
vs closed-date reference date, plus a light pass confirming the shared
filter still applies at row level.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.work_order import WorkOrder
from app.models.work_order_invoice import WorkOrderInvoice
from app.services import receivables_service

NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)


def _make_work_order(**overrides) -> WorkOrder:
    defaults = dict(
        external_number=f"WO-{uuid.uuid4().hex[:8]}",
        source_system="alpha-auto",
        document_date=datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC),
        amount=Decimal("1000.00"),
        closed_date=datetime(2026, 9, 1, tzinfo=UTC),
        debt_amount=Decimal("1000.00"),
    )
    defaults.update(overrides)
    return WorkOrder(**defaults)


class _FakeSettings:
    def __init__(self, revenue_statuses: list[str] | None = None) -> None:
        self.revenue_statuses_list = revenue_statuses or []


def _patch_settings(monkeypatch, revenue_statuses: list[str] | None = None) -> None:
    monkeypatch.setattr(
        receivables_service, "get_settings", lambda: _FakeSettings(revenue_statuses)
    )


# ---- bucket boundaries (pure function) --------------------------------------


@pytest.mark.parametrize(
    ("days_overdue", "expected_bucket"),
    [
        (0, "lt_10"),
        (9, "lt_10"),
        (10, "d10_30"),
        (29, "d10_30"),
        (30, "d30_60"),
        (59, "d30_60"),
        (60, "d60_90"),
        (89, "d60_90"),
        (90, "gte_90"),
        (365, "gte_90"),
    ],
)
def test_bucket_key_boundaries(days_overdue, expected_bucket) -> None:
    assert receivables_service._bucket_key(days_overdue) == expected_bucket


# ---- get_aging_report: reference date ---------------------------------------


def test_uses_closed_date_when_no_invoice_exists(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    wo = _make_work_order(closed_date=datetime(2026, 10, 1, tzinfo=UTC))
    db_session.add(wo)
    db_session.commit()

    report = receivables_service.get_aging_report(db_session, now=NOW)

    assert len(report.rows) == 1
    assert report.rows[0].invoice_date is None
    assert report.rows[0].reference_date == wo.closed_date
    # 2026-10-21 minus 2026-10-01 = 20 days overdue.
    assert report.rows[0].days_overdue == 20
    assert report.rows[0].bucket == "d10_30"


def test_uses_invoice_date_instead_of_closed_date_when_present(
    db_session: Session, monkeypatch
) -> None:
    _patch_settings(monkeypatch)
    # Closed long ago (would be gte_90 on its own), but the invoice was only
    # raised 5 days before `now` - aging should follow the invoice.
    wo = _make_work_order(closed_date=datetime(2026, 1, 1, tzinfo=UTC))
    db_session.add(wo)
    db_session.commit()
    db_session.add(
        WorkOrderInvoice(
            work_order_id=wo.id,
            source_document_id=f"inv-{uuid.uuid4().hex}",
            document_date=datetime(2026, 10, 16, tzinfo=UTC),
            amount=Decimal("1000.00"),
        )
    )
    db_session.commit()

    report = receivables_service.get_aging_report(db_session, now=NOW)

    assert len(report.rows) == 1
    assert report.rows[0].invoice_date == datetime(2026, 10, 16, tzinfo=UTC)
    assert report.rows[0].reference_date == datetime(2026, 10, 16, tzinfo=UTC)
    assert report.rows[0].days_overdue == 5
    assert report.rows[0].bucket == "lt_10"


def test_uses_the_most_recent_invoice_when_several_exist(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    wo = _make_work_order(closed_date=datetime(2026, 9, 1, tzinfo=UTC))
    db_session.add(wo)
    db_session.commit()
    db_session.add_all(
        [
            WorkOrderInvoice(
                work_order_id=wo.id,
                source_document_id=f"inv-{uuid.uuid4().hex}",
                document_date=datetime(2026, 9, 5, tzinfo=UTC),
                amount=Decimal("500.00"),
            ),
            WorkOrderInvoice(
                work_order_id=wo.id,
                source_document_id=f"inv-{uuid.uuid4().hex}",
                document_date=datetime(2026, 10, 19, tzinfo=UTC),
                amount=Decimal("500.00"),
            ),
        ]
    )
    db_session.commit()

    report = receivables_service.get_aging_report(db_session, now=NOW)

    assert report.rows[0].reference_date == datetime(2026, 10, 19, tzinfo=UTC)
    assert report.rows[0].bucket == "lt_10"


# ---- get_aging_report: row order ---------------------------------------


def test_rows_are_ordered_most_recently_closed_first(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    oldest = _make_work_order(closed_date=datetime(2026, 1, 1, tzinfo=UTC))
    newest = _make_work_order(closed_date=datetime(2026, 10, 20, tzinfo=UTC))
    middle = _make_work_order(closed_date=datetime(2026, 6, 1, tzinfo=UTC))
    db_session.add_all([oldest, newest, middle])
    db_session.commit()

    report = receivables_service.get_aging_report(db_session, now=NOW)

    assert [row.work_order_id for row in report.rows] == [newest.id, middle.id, oldest.id]


# ---- get_aging_report: same "what counts as ДЗ" filter as Cockpit ----------


def test_excludes_closed_without_payment(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    wo = _make_work_order(closed_without_payment=True)
    db_session.add(wo)
    db_session.commit()

    report = receivables_service.get_aging_report(db_session, now=NOW)

    assert report.rows == []
    assert report.totals.total == Decimal("0")


def test_excludes_open_work_order(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    wo = _make_work_order(closed_date=None)
    db_session.add(wo)
    db_session.commit()

    report = receivables_service.get_aging_report(db_session, now=NOW)

    assert report.rows == []


def test_excludes_zero_debt(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    wo = _make_work_order(debt_amount=Decimal("0"))
    db_session.add(wo)
    db_session.commit()

    report = receivables_service.get_aging_report(db_session, now=NOW)

    assert report.rows == []


def test_filters_by_revenue_statuses_when_configured(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch, revenue_statuses=["Закрыт"])
    matching = _make_work_order(status="Закрыт")
    other = _make_work_order(status="В работе")
    db_session.add_all([matching, other])
    db_session.commit()

    report = receivables_service.get_aging_report(db_session, now=NOW)

    assert [row.work_order_id for row in report.rows] == [matching.id]


# ---- get_aging_report: totals ------------------------------------------------


def test_totals_sum_debt_per_bucket_and_overall(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    recent = _make_work_order(
        closed_date=datetime(2026, 10, 18, tzinfo=UTC), debt_amount=Decimal("300.00")
    )
    old = _make_work_order(
        closed_date=datetime(2026, 1, 1, tzinfo=UTC), debt_amount=Decimal("700.00")
    )
    db_session.add_all([recent, old])
    db_session.commit()

    report = receivables_service.get_aging_report(db_session, now=NOW)

    assert report.totals.lt_10 == Decimal("300.00")
    assert report.totals.gte_90 == Decimal("700.00")
    assert report.totals.d10_30 == Decimal("0")
    assert report.totals.total == Decimal("1000.00")


def test_row_includes_display_fields(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    wo = _make_work_order(
        status="Закрыт",
        customer_name="Иванов Иван Иванович",
        debt_amount=Decimal("4500.00"),
    )
    db_session.add(wo)
    db_session.commit()

    report = receivables_service.get_aging_report(db_session, now=NOW)

    row = report.rows[0]
    assert row.work_order_number == wo.external_number
    assert row.status == "Закрыт"
    assert row.customer_name == "Иванов Иван Иванович"
    assert row.is_individual_customer is True
    assert row.closed_date == wo.closed_date
    assert row.invoice_date is None
    assert row.debt_amount == Decimal("4500.00")


# ---- get_aging_report: is_individual_customer -------------------------------


def test_is_individual_customer_true_for_a_plain_name(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    wo = _make_work_order(customer_name="Петров Петр Петрович")
    db_session.add(wo)
    db_session.commit()

    report = receivables_service.get_aging_report(db_session, now=NOW)

    assert report.rows[0].is_individual_customer is True


def test_is_individual_customer_false_for_a_legal_entity(db_session: Session, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    wo = _make_work_order(customer_name='ООО "Ромашка"')
    db_session.add(wo)
    db_session.commit()

    report = receivables_service.get_aging_report(db_session, now=NOW)

    assert report.rows[0].is_individual_customer is False
