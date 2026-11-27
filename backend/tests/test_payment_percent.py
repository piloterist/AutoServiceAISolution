from decimal import Decimal

from app.schemas.work_order import effective_payment_percent


def test_percent_is_paid_amount_over_order_amount():
    # The percent 1C sent (50) is ignored when there is a paid amount.
    assert effective_payment_percent(Decimal("2500"), Decimal("10000"), Decimal("50")) == Decimal(
        "25.00"
    )
    assert effective_payment_percent(Decimal("0"), Decimal("10000"), Decimal("50")) == Decimal(
        "0.00"
    )
    # Overpayment is real data, not clamped.
    assert effective_payment_percent(Decimal("12000"), Decimal("10000"), None) == Decimal("120.00")


def test_percent_from_1c_when_there_is_no_paid_amount():
    assert effective_payment_percent(None, Decimal("10000"), Decimal("21.58")) == Decimal("21.58")
    assert effective_payment_percent(None, Decimal("10000"), None) is None


def test_zero_amount_order_keeps_the_1c_percent():
    assert effective_payment_percent(Decimal("0"), Decimal("0"), Decimal("100")) == Decimal("100")
