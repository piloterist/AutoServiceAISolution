"""«Оплачено» и «Долг» заказ-наряда с учётом привязанных платежей (product ask, 2026-11-27).

Если к заказ-наряду привязаны платежи (work_order_payment_events - «История оплат»), то
оплачено - это их сумма, а долг - сумма ЗН минус оплачено. Если платежей нет, оба поля
остаются такими, как пришли из 1С (WorkOrder.paid_amount / debt_amount). Одно правило на всё:
список ЗН, Бюджеты, дебиторка, головной экран - они берут эти выражения, а не поля из 1С.
"""

from sqlalchemy import case, func, select

from app.models.work_order import WorkOrder
from app.models.work_order_payment_event import WorkOrderPaymentEvent


def linked_payments_total():
    """Correlated scalar subquery: the sum of the order's linked payments, NULL when none."""
    return (
        select(func.sum(WorkOrderPaymentEvent.amount))
        .where(
            WorkOrderPaymentEvent.work_order_id == WorkOrder.id,
            WorkOrderPaymentEvent.is_fictitious.is_(False),
        )
        .correlate(WorkOrder)
        .scalar_subquery()
    )


def effective_paid():
    """«Оплачено»: the linked payments' sum, else WorkOrder.paid_amount (may be NULL)."""
    return func.coalesce(linked_payments_total(), WorkOrder.paid_amount)


def effective_debt():
    """«Долг»: amount minus the linked payments, else WorkOrder.debt_amount (may be NULL)."""
    total = linked_payments_total()
    return case((total.is_not(None), WorkOrder.amount - total), else_=WorkOrder.debt_amount)
