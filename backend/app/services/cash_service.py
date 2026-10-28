"""Касса - the cash book of a workshop (product ask, 2026-10-24). See
models/cash_entry.py for what is stored and how the balance works.

Rules enforced here (not in the page):
- ACCESS: a user sees only their own cash desk (their workshop; or, with only
  a department chosen, that department's workshops). A role with "Все
  подразделения" ticked (Settings -> Права доступа, role_tab_visibility.
  all_departments) sees every cash desk. Nobody else's desk is ever returned
  or writable, whatever the page asks for.
- LOCK: entries inside the locked period (AppSettings.cash_lock_from..
  cash_lock_to, both days inclusive) cannot be created, changed, deleted or
  moved into/out of - an old entry can't be quietly rewritten once its days
  are closed.
- CORRECTION (product ask, 2026-10-25): without the role flag "Корректировка
  кассы" (role_tab_visibility.cash_correction) a user may create, change or
  delete entries of TODAY (Moscow clock) only - old and new date both.
- AUDIT: every create/update/delete is written to schedule_audit_log
  (entity_type "cash_entry"), which Settings -> Журнал shows and the dialog's
  "История изменений" button filters down to one entry.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.cash_entry import (
    KIND_CARD_IN,
    KIND_CASH_IN,
    KIND_CASH_OUT,
    KIND_LABELS,
    KINDS,
    CashEntry,
)
from app.models.department import Department
from app.models.employee import Employee
from app.models.role_tab_visibility import RoleTabVisibility
from app.models.schedule_audit_log import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE
from app.models.user import User
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop
from app.models.workshop_source_department import WorkshopSourceDepartment
from app.services import audit_log_service
from app.services.settings_service import get_app_settings

ENTITY_TYPE = "cash_entry"
# How far back the dialog's work-order list reaches (product ask: 100 days).
WORK_ORDER_LOOKBACK_DAYS = 100
WORK_ORDER_LIMIT = 30

_CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Two decimals, kopeks - how every amount is stored and shown."""
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


class CashError(Exception):
    """Base class - the endpoint maps each subclass to an HTTP status."""


class CashForbidden(CashError):
    pass


class CashNotFound(CashError):
    pass


class CashLocked(CashError):
    pass


class CashInvalid(CashError):
    pass


@dataclass
class CashAccess:
    all_departments: bool
    workshop_ids: set[uuid.UUID]
    can_correct: bool = False

    def allows(self, workshop_id: uuid.UUID) -> bool:
        return workshop_id in self.workshop_ids


def get_access(db: Session, user_id: uuid.UUID | None) -> CashAccess:
    """Which cash desks this user may see (see module docstring)."""
    user = db.get(User, user_id) if user_id else None
    if user is None:
        return CashAccess(False, set())

    role_row = db.scalar(select(RoleTabVisibility).where(RoleTabVisibility.role == user.role))
    can_correct = role_row is not None and role_row.cash_correction
    if role_row is not None and role_row.all_departments:
        return CashAccess(True, set(db.scalars(select(Workshop.id))), can_correct)
    if user.workshop_id is not None:
        return CashAccess(False, {user.workshop_id}, can_correct)
    if user.department_id is not None:
        return CashAccess(
            False,
            set(
                db.scalars(select(Workshop.id).where(Workshop.department_id == user.department_id))
            ),
            can_correct,
        )
    return CashAccess(False, set(), can_correct)


def _require(access: CashAccess, workshop_id: uuid.UUID) -> None:
    if not access.allows(workshop_id):
        raise CashForbidden("Нет доступа к этой кассе")


def today_msk() -> date:
    return (datetime.now(UTC) + timedelta(hours=3)).date()


def _ensure_may_edit(access: CashAccess, *days: date) -> None:
    if access.can_correct:
        return
    today = today_msk()
    if any(day != today for day in days):
        raise CashForbidden(
            "Без права «Корректировка кассы» записи можно вносить и менять "
            "только за сегодняшний день"
        )


# ---- lock --------------------------------------------------------------------


def lock_period(db: Session) -> tuple[date | None, date | None]:
    settings = get_app_settings(db)
    if settings.cash_lock_from is None or settings.cash_lock_to is None:
        return None, None
    return settings.cash_lock_from, settings.cash_lock_to


def is_locked(db: Session, day: date) -> bool:
    lock_from, lock_to = lock_period(db)
    return lock_from is not None and lock_to is not None and lock_from <= day <= lock_to


def _ensure_unlocked(db: Session, *days: date) -> None:
    for day in days:
        if is_locked(db, day):
            lock_from, lock_to = lock_period(db)
            raise CashLocked(
                f"Дата {day.strftime('%d.%m.%Y')} в заблокированном периоде "
                f"({lock_from.strftime('%d.%m.%Y')} — {lock_to.strftime('%d.%m.%Y')}): "
                "изменения кассы закрыты"
            )


# ---- context / book ----------------------------------------------------------


def get_context(db: Session, user_id: uuid.UUID | None) -> dict:
    access = get_access(db, user_id)
    rows = db.execute(
        select(Workshop, Department.name)
        .join(Department, Department.id == Workshop.department_id)
        .where(Workshop.id.in_(access.workshop_ids))
        .order_by(Department.name, Workshop.workshop_type)
    ).all()
    workshops = [
        {
            "id": workshop.id,
            "department_id": workshop.department_id,
            "department_name": department_name,
            "workshop_type": workshop.workshop_type,
        }
        for workshop, department_name in rows
    ]

    user = db.get(User, user_id) if user_id else None
    default_id = None
    if user is not None and user.workshop_id in access.workshop_ids:
        default_id = user.workshop_id
    elif workshops:
        default_id = workshops[0]["id"]

    lock_from, lock_to = lock_period(db)
    return {
        "current_employee_id": user.employee_id if user is not None else None,
        "card_holders": get_card_holders(db),
        "workshops": workshops,
        "default_workshop_id": default_id,
        "all_departments": access.all_departments,
        "can_correct": access.can_correct,
        "today": today_msk(),
        "lock_from": lock_from,
        "lock_to": lock_to,
    }


def get_card_holders(db: Session) -> list[dict]:
    """The people a personal card can be tied to: every employee of the directory
    (product ask, 2026-10-29: no limit by specialty)."""
    employees = db.scalars(select(Employee).order_by(Employee.full_name))
    return [{"id": employee.id, "name": employee.full_name} for employee in employees]


SCOPES = ("all", "cash", "personal")


def _scope_conditions(scope: str, card_holder_id: uuid.UUID | None) -> list:
    """Which entries belong to the shown part of the book: all of them, the cash
    ones (without personal cards), the personal-card ones, or one person's card."""
    if card_holder_id is not None:
        return [CashEntry.personal_card.is_(True), CashEntry.card_holder_id == card_holder_id]
    if scope == "cash":
        return [CashEntry.personal_card.is_(False)]
    if scope == "personal":
        return [CashEntry.personal_card.is_(True)]
    return []


def card_balance_today(db: Session, access: CashAccess, holder_id: uuid.UUID) -> Decimal:
    """A person's personal-card balance up to today (Moscow): their marked cash in
    minus cash out, over every desk the caller may see."""
    rows = db.execute(
        select(CashEntry.kind, func.coalesce(func.sum(CashEntry.amount), 0))
        .where(
            CashEntry.workshop_id.in_(access.workshop_ids),
            CashEntry.personal_card.is_(True),
            CashEntry.card_holder_id == holder_id,
            CashEntry.entry_date <= today_msk(),
        )
        .group_by(CashEntry.kind)
    ).all()
    totals = {kind: Decimal(total) for kind, total in rows}
    return _money(totals.get(KIND_CASH_IN, Decimal(0)) - totals.get(KIND_CASH_OUT, Decimal(0)))


def _sum(db: Session, workshop_id: uuid.UUID, kind: str, *conditions) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(CashEntry.amount), 0)).where(
            CashEntry.workshop_id == workshop_id, CashEntry.kind == kind, *conditions
        )
    )
    return Decimal(total or 0)


def get_book(
    db: Session,
    access: CashAccess,
    workshop_id: uuid.UUID,
    date_from: date,
    date_to: date,
    scope: str = "all",
    card_holder_id: uuid.UUID | None = None,
) -> dict:
    """The cash book for [date_from, date_to]: the balance at the start (all
    cash in minus cash out before date_from), the period's entries and
    totals, and the balance at the end. `scope` narrows it to the cash entries
    (no personal cards), the personal-card ones, or - with `card_holder_id` - one
    person's card (balances then count only those entries)."""
    _require(access, workshop_id)
    if date_to < date_from:
        raise CashInvalid("Дата «по» не может быть раньше даты «с»")
    if scope not in SCOPES:
        raise CashInvalid(f"Неизвестный режим кассы: {scope}")
    scope_conditions = _scope_conditions(scope, card_holder_id)

    before = CashEntry.entry_date < date_from
    opening = _sum(db, workshop_id, KIND_CASH_IN, before, *scope_conditions) - _sum(
        db, workshop_id, KIND_CASH_OUT, before, *scope_conditions
    )

    entries = list(
        db.scalars(
            select(CashEntry)
            .where(
                CashEntry.workshop_id == workshop_id,
                CashEntry.entry_date >= date_from,
                CashEntry.entry_date <= date_to,
                *scope_conditions,
            )
            .order_by(CashEntry.entry_date, CashEntry.created_at)
        )
    )
    totals = {kind: Decimal(0) for kind in KINDS}
    for entry in entries:
        totals[entry.kind] += entry.amount

    lock_from, lock_to = lock_period(db)
    return {
        "workshop_id": workshop_id,
        "date_from": date_from,
        "date_to": date_to,
        "opening": _money(opening),
        "closing": _money(opening + totals[KIND_CASH_IN] - totals[KIND_CASH_OUT]),
        "totals": {
            "cash_in": _money(totals[KIND_CASH_IN]),
            "card_in": _money(totals[KIND_CARD_IN]),
            "cash_out": _money(totals[KIND_CASH_OUT]),
        },
        "entries": [
            {
                **{c: getattr(e, c) for c in _ENTRY_FIELDS},
                "locked": lock_from is not None
                and lock_to is not None
                and lock_from <= e.entry_date <= lock_to,
            }
            for e in entries
        ],
        "lock_from": lock_from,
        "lock_to": lock_to,
        "scope": scope,
        "card_holder_id": card_holder_id,
        "card_balance_today": (
            card_balance_today(db, access, card_holder_id) if card_holder_id is not None else None
        ),
    }


_ENTRY_FIELDS = (
    "id",
    "workshop_id",
    "entry_date",
    "kind",
    "amount",
    "comment",
    "work_order_id",
    "work_order_number",
    "personal_card",
    "card_holder_id",
    "card_holder_name",
    "created_by_name",
    "created_at",
    "updated_by_name",
    "updated_at",
)


def search_entries(
    db: Session, access: CashAccess, workshop_id: uuid.UUID, q: str
) -> list[CashEntry]:
    """Entries of the desk whose work-order number OR comment contains the
    typed text (one field, product ask 2026-10-26), EARLIEST first (by day,
    then by when they were entered) - the page jumps to the first and the
    arrows walk through the rest."""
    _require(access, workshop_id)
    text = q.strip()
    if not text:
        return []
    return list(
        db.scalars(
            select(CashEntry)
            .where(
                CashEntry.workshop_id == workshop_id,
                or_(
                    CashEntry.work_order_number.ilike(f"%{text}%"),
                    CashEntry.comment.ilike(f"%{text}%"),
                ),
            )
            .order_by(CashEntry.entry_date, CashEntry.created_at)
            .limit(200)
        )
    )


# ---- work-order drop-down ----------------------------------------------------


def search_work_orders(
    db: Session, access: CashAccess, workshop_id: uuid.UUID, q: str
) -> list[WorkOrder]:
    """The workshop's work orders of the last 100 days (by the workshop's
    mapped 1C departments, Settings -> Подразделения), newest first,
    narrowed by the typed text over number / car / VIN / customer."""
    _require(access, workshop_id)
    departments = list(
        db.scalars(
            select(WorkshopSourceDepartment.source_department).where(
                WorkshopSourceDepartment.workshop_id == workshop_id
            )
        )
    )
    if not departments:
        return []

    cutoff = datetime.now(UTC) - timedelta(days=WORK_ORDER_LOOKBACK_DAYS)
    conditions = [WorkOrder.department.in_(departments), WorkOrder.created_date >= cutoff]
    text = q.strip()
    if text:
        like = f"%{text}%"
        conditions.append(
            or_(
                WorkOrder.external_number.ilike(like),
                WorkOrder.vehicle_description.ilike(like),
                WorkOrder.vin.ilike(like),
                WorkOrder.customer_name.ilike(like),
            )
        )
    return list(
        db.scalars(
            select(WorkOrder)
            .where(*conditions)
            .order_by(WorkOrder.created_date.desc())
            .limit(WORK_ORDER_LIMIT)
        )
    )


# ---- writes ------------------------------------------------------------------


def _clean(text: str | None) -> str | None:
    text = (text or "").strip()
    return text or None


def _audit_values(entry: CashEntry, workshop_label: str | None = None) -> dict:
    values = {
        "kind": KIND_LABELS[entry.kind],
        "entry_date": entry.entry_date.isoformat(),
        "amount": str(entry.amount),
        "comment": entry.comment,
        "work_order_number": entry.work_order_number,
        "card_holder": entry.card_holder_name if entry.personal_card else None,
    }
    if workshop_label is not None:
        values["workshop"] = workshop_label
    return values


def _workshop_label(db: Session, workshop_id: uuid.UUID) -> str:
    row = db.execute(
        select(Department.name, Workshop.workshop_type)
        .join(Workshop, Workshop.department_id == Department.id)
        .where(Workshop.id == workshop_id)
    ).first()
    return f"{row[0]} — {row[1]}" if row else str(workshop_id)


def _resolve_work_order(
    db: Session, work_order_id: uuid.UUID | None, typed_number: str | None
) -> tuple[uuid.UUID | None, str | None]:
    """A picked work order wins (its number is copied); otherwise whatever was
    typed by hand is kept as plain text."""
    if work_order_id is not None:
        work_order = db.get(WorkOrder, work_order_id)
        if work_order is None:
            raise CashInvalid("Заказ-наряд не найден")
        return work_order.id, work_order.external_number
    return None, _clean(typed_number)


def _validate_kind(kind: str) -> None:
    if kind not in KINDS:
        raise CashInvalid(f"Неизвестный раздел кассы: {kind}")


def _resolve_card_holder(
    db: Session,
    access: CashAccess,
    *,
    kind: str,
    personal_card: bool,
    requested_id: uuid.UUID | None,
    existing_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
) -> tuple[bool, uuid.UUID | None, str | None]:
    """(personal_card, holder employee id, holder name) to store. The holder
    defaults to the one already on the entry, else to the employee linked to whoever
    makes it (users.employee_id); naming someone else (or changing the holder)
    needs "Корректировка кассы". Any employee of the directory can hold a card."""
    if not personal_card:
        return False, None, None
    if kind == KIND_CARD_IN:
        raise CashInvalid("Личная карта указывается только у прихода и расхода НАЛ")
    actor = db.get(User, actor_user_id) if actor_user_id else None
    own_id = actor.employee_id if actor is not None else None
    holder_id = requested_id or existing_id or own_id
    if holder_id is None:
        raise CashInvalid(
            "Выберите сотрудника для личной карты (ваш пользователь не связан с сотрудником)"
        )
    own_first_pick = existing_id is None and holder_id == own_id
    if holder_id != existing_id and not own_first_pick and not access.can_correct:
        raise CashForbidden(
            "Менять сотрудника личной карты может только пользователь с правом "
            "«Корректировка кассы»"
        )
    holder = db.get(Employee, holder_id)
    if holder is None:
        raise CashInvalid("Сотрудник не найден")
    return True, holder.id, holder.full_name


def create_entry(
    db: Session,
    access: CashAccess,
    *,
    workshop_id: uuid.UUID,
    entry_date: date,
    kind: str,
    amount: Decimal,
    comment: str | None,
    work_order_id: uuid.UUID | None,
    work_order_number: str | None,
    actor_user_id: uuid.UUID | None,
    actor_name: str,
    personal_card: bool = False,
    card_holder_id: uuid.UUID | None = None,
) -> CashEntry:
    _require(access, workshop_id)
    _ensure_may_edit(access, entry_date)
    _validate_kind(kind)
    amount = _money(amount)
    if amount <= 0:
        raise CashInvalid("Сумма должна быть больше нуля")
    _ensure_unlocked(db, entry_date)
    resolved_id, resolved_number = _resolve_work_order(db, work_order_id, work_order_number)
    is_card, holder_id, holder_name = _resolve_card_holder(
        db,
        access,
        kind=kind,
        personal_card=personal_card,
        requested_id=card_holder_id,
        existing_id=None,
        actor_user_id=actor_user_id,
    )

    entry = CashEntry(
        workshop_id=workshop_id,
        entry_date=entry_date,
        kind=kind,
        amount=amount,
        comment=_clean(comment),
        work_order_id=resolved_id,
        work_order_number=resolved_number,
        personal_card=is_card,
        card_holder_id=holder_id,
        card_holder_name=holder_name,
        created_by_id=actor_user_id,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    audit_log_service.record_change(
        db,
        entity_type=ENTITY_TYPE,
        entity_id=entry.id,
        action=ACTION_CREATE,
        changes={
            field: {"old": None, "new": value}
            for field, value in _audit_values(entry, _workshop_label(db, workshop_id)).items()
        },
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        work_order_id=entry.work_order_id,
    )
    db.commit()
    db.refresh(entry)
    return entry


def _load(db: Session, access: CashAccess, entry_id: uuid.UUID) -> CashEntry:
    entry = db.get(CashEntry, entry_id)
    if entry is None:
        raise CashNotFound("Запись кассы не найдена")
    _require(access, entry.workshop_id)
    return entry


def _delete(
    db: Session, entry: CashEntry, actor_user_id: uuid.UUID | None, actor_name: str
) -> None:
    audit_log_service.record_change(
        db,
        entity_type=ENTITY_TYPE,
        entity_id=entry.id,
        action=ACTION_DELETE,
        changes={
            field: {"old": value, "new": None}
            for field, value in _audit_values(entry, _workshop_label(db, entry.workshop_id)).items()
        },
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        work_order_id=entry.work_order_id,
    )
    db.delete(entry)
    db.commit()


def update_entry(
    db: Session,
    access: CashAccess,
    entry_id: uuid.UUID,
    *,
    entry_date: date,
    kind: str,
    amount: Decimal,
    comment: str | None,
    work_order_id: uuid.UUID | None,
    work_order_number: str | None,
    actor_user_id: uuid.UUID | None,
    actor_name: str,
    personal_card: bool = False,
    card_holder_id: uuid.UUID | None = None,
) -> CashEntry | None:
    """Changes any field of an entry. A zero amount deletes it (returns None).
    Both the old and the new date must be outside the locked period."""
    entry = _load(db, access, entry_id)
    _ensure_may_edit(access, entry.entry_date, entry_date)
    _validate_kind(kind)
    amount = _money(amount)
    if amount < 0:
        raise CashInvalid("Сумма не может быть отрицательной")
    _ensure_unlocked(db, entry.entry_date, entry_date)

    if amount == 0:
        _delete(db, entry, actor_user_id, actor_name)
        return None

    before = _audit_values(entry)
    resolved_id, resolved_number = _resolve_work_order(db, work_order_id, work_order_number)
    is_card, holder_id, holder_name = _resolve_card_holder(
        db,
        access,
        kind=kind,
        personal_card=personal_card,
        requested_id=card_holder_id,
        existing_id=entry.card_holder_id if entry.personal_card else None,
        actor_user_id=actor_user_id,
    )
    entry.entry_date = entry_date
    entry.kind = kind
    entry.amount = amount
    entry.comment = _clean(comment)
    entry.work_order_id = resolved_id
    entry.work_order_number = resolved_number
    entry.personal_card = is_card
    entry.card_holder_id = holder_id
    entry.card_holder_name = holder_name
    after = _audit_values(entry)

    changes = {
        field: {"old": before[field], "new": after[field]}
        for field in after
        if before[field] != after[field]
    }
    if changes:
        entry.updated_by_id = actor_user_id
        entry.updated_by_name = actor_name
        entry.updated_at = datetime.now(UTC)
        audit_log_service.record_change(
            db,
            entity_type=ENTITY_TYPE,
            entity_id=entry.id,
            action=ACTION_UPDATE,
            changes=changes,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            work_order_id=entry.work_order_id,
        )
    db.commit()
    db.refresh(entry)
    return entry


def delete_entry(
    db: Session,
    access: CashAccess,
    entry_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None,
    actor_name: str,
) -> None:
    entry = _load(db, access, entry_id)
    _ensure_may_edit(access, entry.entry_date)
    _ensure_unlocked(db, entry.entry_date)
    _delete(db, entry, actor_user_id, actor_name)
