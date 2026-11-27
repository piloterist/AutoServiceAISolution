from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.models.work_order import WorkOrder
from app.models.work_order_payment_event import WorkOrderPaymentEvent
from app.schemas.work_order import effective_payment
from app.services.order_payments import effective_paid
from app.services.payment_duplicates import mark_duplicate_payments


def test_linked_payments_give_paid_debt_and_percent():
    # ПМ00000009: 1C says paid 0 / debt 104033.68 / 0%, but a payment of 84033.68 is linked.
    paid, debt, percent = effective_payment(
        Decimal("84033.68"), Decimal("104033.68"), Decimal("0"), Decimal("104033.68"), Decimal("0")
    )
    assert paid == Decimal("84033.68")
    assert debt == Decimal("20000.00")
    assert percent == Decimal("80.78")


def test_overpayment_is_not_clamped():
    paid, debt, percent = effective_payment(Decimal("12000"), Decimal("10000"), None, None, None)
    assert (paid, debt, percent) == (Decimal("12000"), Decimal("-2000"), Decimal("120.00"))


def test_without_linked_payments_all_fields_stay_as_1c_sent_them():
    assert effective_payment(
        None, Decimal("10000"), Decimal("2500"), Decimal("7500"), Decimal("21.58")
    ) == (Decimal("2500"), Decimal("7500"), Decimal("21.58"))
    assert effective_payment(None, Decimal("10000"), None, None, None) == (None, None, None)


def test_zero_amount_order_keeps_the_1c_percent():
    paid, debt, percent = effective_payment(
        Decimal("100"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("55")
    )
    assert (paid, debt, percent) == (Decimal("100"), Decimal("-100"), Decimal("55"))


# --- «Фиктивные» платежи: дубли строк одного платежа ---


def _order(db, amount, number="WO-DUP"):
    order = WorkOrder(
        external_number=number,
        source_system="alpha-auto",
        document_date=datetime(2026, 5, 1, tzinfo=UTC),
        amount=Decimal(amount),
    )
    db.add(order)
    db.flush()
    return order


def _payment(db, order, amount, line, doc="doc-1"):
    event = WorkOrderPaymentEvent(
        work_order_id=order.id,
        paid_at=datetime(2026, 5, 4, tzinfo=UTC),
        amount=Decimal(amount),
        source_document_id=doc,
        line_number=line,
    )
    db.add(event)
    return event


def _fictitious(db, order):
    rows = db.scalars(
        select(WorkOrderPaymentEvent)
        .where(WorkOrderPaymentEvent.work_order_id == order.id)
        .order_by(WorkOrderPaymentEvent.line_number)
    ).all()
    return [row.is_fictitious for row in rows]


def test_paid_twice_marks_the_second_line_and_it_is_not_counted(db_session):
    order = _order(db_session, "400900")
    _payment(db_session, order, "400900", line=7)
    _payment(db_session, order, "400900", line=10)
    db_session.commit()

    assert mark_duplicate_payments(db_session, [order.id]) == 1
    db_session.commit()
    assert _fictitious(db_session, order) == [False, True]
    paid = db_session.execute(select(effective_paid()).where(WorkOrder.id == order.id)).scalar_one()
    assert paid == Decimal("400900")  # not 801800

    # idempotent: a second run changes nothing
    assert mark_duplicate_payments(db_session, [order.id]) == 0


def test_paid_three_times_keeps_one_line(db_session):
    order = _order(db_session, "1000")
    for line in (1, 2, 3):
        _payment(db_session, order, "1000", line=line)
    db_session.commit()

    mark_duplicate_payments(db_session, [order.id])
    assert _fictitious(db_session, order) == [False, True, True]


def test_genuine_payments_are_not_marked(db_session):
    # equal parts that add up to the order, different amounts, a plain overpayment: no dups
    parts = _order(db_session, "1000", "WO-PARTS")
    _payment(db_session, parts, "500", line=1, doc="a")
    _payment(db_session, parts, "500", line=2, doc="b")
    mixed = _order(db_session, "1000", "WO-MIXED")
    _payment(db_session, mixed, "600", line=1, doc="c")
    _payment(db_session, mixed, "900", line=2, doc="d")
    over = _order(db_session, "1000", "WO-OVER")
    _payment(db_session, over, "1200", line=1, doc="e")
    db_session.commit()

    assert mark_duplicate_payments(db_session) == 0
    assert _fictitious(db_session, parts) == [False, False]
    assert _fictitious(db_session, mixed) == [False, False]
    assert _fictitious(db_session, over) == [False]


def test_mark_is_cleared_when_the_rule_stops_applying(db_session):
    order = _order(db_session, "1000")
    _payment(db_session, order, "1000", line=1)
    _payment(db_session, order, "1000", line=2)
    db_session.commit()
    mark_duplicate_payments(db_session, [order.id])
    assert _fictitious(db_session, order) == [False, True]

    order.amount = Decimal("1500")  # the order was re-priced: 2000 is no longer k x 1500
    db_session.commit()
    mark_duplicate_payments(db_session, [order.id])
    assert _fictitious(db_session, order) == [False, False]
