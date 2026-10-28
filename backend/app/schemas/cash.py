"""Contract for the Касса page - see services/cash_service.py."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CashWorkshopOut(BaseModel):
    """One cash desk (a workshop), as a tab on the page."""

    id: uuid.UUID
    department_id: uuid.UUID
    department_name: str
    workshop_type: str


class CashCardHolderOut(BaseModel):
    """An employee who can hold a personal card (specialty "Мастер приёмщик")."""

    id: uuid.UUID
    name: str


class CashContextResponse(BaseModel):
    # Only the cash desks the acting user may see - never the rest.
    workshops: list[CashWorkshopOut]
    default_workshop_id: uuid.UUID | None
    # The role has "Все подразделения" ticked (Settings -> Права доступа).
    all_departments: bool
    # The role has "Корректировка кассы": may edit any day, not only today.
    can_correct: bool
    # Today on the Moscow clock - the only day editable without that right.
    today: date
    lock_from: date | None
    lock_to: date | None
    # The employee linked to the acting user (the default card holder of a new
    # entry; None when the user is not linked) and the people a personal card can be
    # tied to.
    current_employee_id: uuid.UUID | None
    card_holders: list[CashCardHolderOut]


class CashEntryOut(BaseModel):
    id: uuid.UUID
    workshop_id: uuid.UUID
    entry_date: date
    kind: str
    amount: Decimal
    comment: str | None
    work_order_id: uuid.UUID | None
    work_order_number: str | None
    personal_card: bool
    card_holder_id: uuid.UUID | None
    card_holder_name: str | None
    created_by_name: str
    created_at: datetime
    updated_by_name: str | None
    updated_at: datetime | None
    # Inside the locked period: shown, but not editable.
    locked: bool

    model_config = {"from_attributes": True}


class CashTotals(BaseModel):
    cash_in: Decimal
    card_in: Decimal
    cash_out: Decimal


class CashBookResponse(BaseModel):
    workshop_id: uuid.UUID
    date_from: date
    date_to: date
    # Cash in the drawer at the start of date_from / the end of date_to:
    # everything before date_from (cash in - cash out), then the period.
    opening: Decimal
    closing: Decimal
    totals: CashTotals
    entries: list[CashEntryOut]
    lock_from: date | None
    lock_to: date | None
    # Which part of the book this is: "all" / "cash" (without personal cards) /
    # "personal" (personal cards only); with card_holder_id: that person's card.
    scope: str
    card_holder_id: uuid.UUID | None
    # Only with card_holder_id: the card balance as of today over every desk the
    # caller may see (independent of the shown period).
    card_balance_today: Decimal | None


class CashEntryResult(BaseModel):
    """Outcome of editing an entry: it was changed (`entry`) or - with a zero
    amount - deleted."""

    deleted: bool
    entry: CashEntryOut | None


class CashEntryWrite(BaseModel):
    workshop_id: uuid.UUID
    entry_date: date
    kind: str
    # On update, 0 deletes the entry (product ask: "если сумму обнулить,
    # то запись должна удалиться"); on create it must be positive.
    amount: Decimal = Field(ge=0)
    comment: str | None = None
    work_order_id: uuid.UUID | None = None
    work_order_number: str | None = Field(default=None, max_length=100)
    # Only for Приход НАЛ / Расход НАЛ. The holder defaults to whoever makes the
    # entry; picking someone else needs "Корректировка кассы".
    personal_card: bool = False
    card_holder_id: uuid.UUID | None = None


class CashWorkOrderOut(BaseModel):
    """A work order offered in the dialog's drop-down."""

    id: uuid.UUID
    external_number: str
    vehicle_description: str | None
    customer_name: str | None
    status: str | None
    document_date: datetime


class CashSearchHit(BaseModel):
    """One entry found by work-order number (the page's search + arrows)."""

    id: uuid.UUID
    entry_date: date
    kind: str
    work_order_number: str | None
