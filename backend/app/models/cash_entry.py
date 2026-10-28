"""Касса (cash book) - one row per money movement of a workshop's cash desk
(product ask, 2026-10-24: replaces the monthly Google Sheet kept per цех,
with a sheet per day and three sections).

Three kinds of movement, shown as three columns:
- KIND_CASH_IN  - "Приход НАЛ": cash received;
- KIND_CARD_IN  - "Приход КАРТА": card payments - listed and totalled, but they
  are NOT money in the drawer, so they never touch the cash balance;
- KIND_CASH_OUT - "Расход НАЛ": cash paid out.

The cash balance is never stored: it is always opening + cash in - cash out
over the entries, so correcting an old entry (or entering one for a past day)
re-flows every later balance automatically. The very first balance is simply
a "Приход НАЛ" entry on the first day (comment "Начальный остаток").

A cash desk belongs to a Workshop (цех) - the department/workshop tabs on the
page are the same ones the Planner has.

Every change is also written to schedule_audit_log (entity_type "cash_entry",
see services/cash_service.py); the created_by/updated_by columns here only
answer the common "who made / last touched this row" question at a glance.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

KIND_CASH_IN = "cash_in"
KIND_CARD_IN = "card_in"
KIND_CASH_OUT = "cash_out"
KINDS = (KIND_CASH_IN, KIND_CARD_IN, KIND_CASH_OUT)

KIND_LABELS = {
    KIND_CASH_IN: "Приход НАЛ",
    KIND_CARD_IN: "Приход КАРТА",
    KIND_CASH_OUT: "Расход НАЛ",
}


class CashEntry(Base):
    __tablename__ = "cash_entries"
    __table_args__ = (Index("ix_cash_entries_workshop_id_entry_date", "workshop_id", "entry_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # RESTRICT, not CASCADE: deleting a workshop must never silently wipe its
    # cash history.
    workshop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workshops.id", ondelete="RESTRICT"), nullable=False
    )
    # The cash-book day the entry belongs to (picked in the calendar) - any
    # day, past or future, unless inside the locked period (AppSettings.
    # cash_lock_from/cash_lock_to).
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "Личная карта" (product ask, 2026-10-29): a Приход НАЛ / Расход НАЛ that went
    # through a person's own card, not through the drawer. The person is an employee
    # of the directory with the specialty "Мастер приёмщик" - by default the one linked
    # to the user who made the entry (users.employee_id), another only for a role with
    # "Корректировка кассы". The card balance of a person is these entries: in - out.
    # Never set on "Приход КАРТА".
    personal_card: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    card_holder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Name snapshot, same reason as created_by_name.
    card_holder_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Optional link to a work order: picked from the workshop's recent ones
    # (work_order_id set, work_order_number copied from it) or typed by hand
    # when it was not found (work_order_number only).
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True
    )
    work_order_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # SET NULL + a name snapshot, same as schedule_audit_log: deleting a user
    # must not erase who made a cash entry.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # NULL until the entry is changed after creation.
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CashEntry {self.entry_date} {self.kind} {self.amount}>"
