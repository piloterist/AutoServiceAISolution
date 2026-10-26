"""Tests for the Касса (cash book) - services/cash_service.py and its API."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_entry import KIND_CARD_IN, KIND_CASH_IN, KIND_CASH_OUT, CashEntry
from app.models.department import Department
from app.models.role_tab_visibility import RoleTabVisibility
from app.models.schedule_audit_log import ScheduleAuditLog
from app.models.user import User
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop
from app.models.workshop_source_department import WorkshopSourceDepartment
from app.services import cash_service
from app.services.cash_service import (
    CashAccess,
    CashForbidden,
    CashInvalid,
    CashLocked,
    CashNotFound,
)

DAY = date(2026, 10, 10)


def _workshop(db: Session, dept: Department, workshop_type: str) -> Workshop:
    workshop = Workshop(
        department_id=dept.id,
        workshop_type=workshop_type,
        posts_count=1,
        start_time="08:00:00",
        end_time="20:00:00",
        working_days=[0],
    )
    db.add(workshop)
    db.flush()
    return workshop


def _user(db: Session, role: str = "Сотрудник", **kw) -> User:
    user = User(
        full_name=kw.pop("full_name", "Кассир Кассиров"),
        login=f"u-{uuid.uuid4().hex[:8]}",
        password_hash="x",
        role=role,
        **kw,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def world(db_session: Session) -> dict:
    kahovka = Department(name="Каховка")
    solntsevo = Department(name="Солнцево")
    db_session.add_all([kahovka, solntsevo])
    db_session.flush()
    body = _workshop(db_session, kahovka, "Кузовной")
    mech = _workshop(db_session, kahovka, "Слесарный")
    other = _workshop(db_session, solntsevo, "Кузовной")
    # The test cashier may correct any day (cash_correction); the today-only
    # rule has its own tests below.
    db_session.add(RoleTabVisibility(role="Кассир", visible_tabs=["/cash"], cash_correction=True))
    cashier = _user(db_session, role="Кассир", workshop_id=body.id, department_id=kahovka.id)
    db_session.commit()
    return {
        "kahovka": kahovka,
        "body": body,
        "mech": mech,
        "other": other,
        "cashier": cashier,
    }


def _access(db: Session, user: User) -> CashAccess:
    return cash_service.get_access(db, user.id)


def _add(
    db: Session,
    world: dict,
    kind: str,
    amount: str,
    day: date = DAY,
    *,
    workshop: str = "body",
    comment: str | None = None,
    work_order_number: str | None = None,
):
    return cash_service.create_entry(
        db,
        _access(db, world["cashier"]),
        workshop_id=world[workshop].id,
        entry_date=day,
        kind=kind,
        amount=Decimal(amount),
        comment=comment,
        work_order_id=None,
        work_order_number=work_order_number,
        actor_user_id=world["cashier"].id,
        actor_name="Кассир Кассиров",
    )


# ---- access ------------------------------------------------------------------


def test_user_sees_only_their_own_workshop(db_session: Session, world: dict) -> None:
    access = _access(db_session, world["cashier"])

    assert access.all_departments is False
    assert access.workshop_ids == {world["body"].id}
    context = cash_service.get_context(db_session, world["cashier"].id)
    assert [w["id"] for w in context["workshops"]] == [world["body"].id]
    assert context["default_workshop_id"] == world["body"].id


def test_user_with_only_a_department_sees_its_workshops(db_session: Session, world: dict) -> None:
    user = _user(db_session, department_id=world["kahovka"].id)
    db_session.commit()

    assert _access(db_session, user).workshop_ids == {world["body"].id, world["mech"].id}


def test_user_without_workshop_or_department_sees_nothing(db_session: Session) -> None:
    user = _user(db_session)
    db_session.commit()

    access = _access(db_session, user)
    assert access.workshop_ids == set()
    assert cash_service.get_context(db_session, user.id)["workshops"] == []
    assert cash_service.get_context(db_session, None)["workshops"] == []


def test_role_with_all_departments_sees_every_cash_desk(db_session: Session, world: dict) -> None:
    db_session.add(
        RoleTabVisibility(role="Бухгалтер", visible_tabs=["/cash"], all_departments=True)
    )
    accountant = _user(db_session, role="Бухгалтер")
    db_session.commit()

    access = _access(db_session, accountant)

    assert access.all_departments is True
    assert access.workshop_ids == {world["body"].id, world["mech"].id, world["other"].id}


def test_other_workshops_are_never_readable_or_writable(db_session: Session, world: dict) -> None:
    access = _access(db_session, world["cashier"])

    with pytest.raises(CashForbidden):
        cash_service.get_book(db_session, access, world["other"].id, DAY, DAY)
    with pytest.raises(CashForbidden):
        _add(db_session, world, KIND_CASH_IN, "100", workshop="other")
    assert cash_service.search_work_orders(db_session, access, world["body"].id, "") == []


# ---- balances ----------------------------------------------------------------


def test_book_computes_balances_and_card_does_not_touch_cash(
    db_session: Session, world: dict
) -> None:
    _add(
        db_session,
        world,
        KIND_CASH_IN,
        "138409.55",
        DAY - timedelta(days=1),
        comment="Начальный остаток",
    )
    _add(db_session, world, KIND_CASH_IN, "2500")
    _add(db_session, world, KIND_CASH_IN, "5000")
    _add(db_session, world, KIND_CARD_IN, "8000")
    _add(db_session, world, KIND_CARD_IN, "30500")
    _add(db_session, world, KIND_CASH_OUT, "37500")
    _add(db_session, world, KIND_CASH_OUT, "14000")
    access = _access(db_session, world["cashier"])

    day = cash_service.get_book(db_session, access, world["body"].id, DAY, DAY)

    assert day["opening"] == Decimal("138409.55")
    assert day["totals"] == {
        "cash_in": Decimal("7500.00"),
        "card_in": Decimal("38500.00"),
        "cash_out": Decimal("51500.00"),
    }
    # cash only: 138 409,55 + 7 500 - 51 500 (the 38 500 by card is not cash)
    assert day["closing"] == Decimal("94409.55")
    assert [e["amount"] for e in day["entries"]][:2] == [Decimal("2500.00"), Decimal("5000.00")]

    # The next day opens with that closing balance.
    next_day = cash_service.get_book(
        db_session, access, world["body"].id, DAY + timedelta(days=1), DAY + timedelta(days=1)
    )
    assert next_day["opening"] == day["closing"]
    assert next_day["closing"] == day["closing"]


def test_first_day_starts_at_zero_and_a_period_spans_days(db_session: Session, world: dict) -> None:
    _add(db_session, world, KIND_CASH_IN, "1000", DAY)
    _add(db_session, world, KIND_CASH_OUT, "300", DAY + timedelta(days=1))
    _add(db_session, world, KIND_CASH_IN, "50", DAY + timedelta(days=2))
    access = _access(db_session, world["cashier"])

    period = cash_service.get_book(
        db_session, access, world["body"].id, DAY, DAY + timedelta(days=2)
    )

    assert period["opening"] == Decimal("0")
    assert period["closing"] == Decimal("750.00")
    assert len(period["entries"]) == 3


def test_correcting_an_old_entry_reflows_later_balances(db_session: Session, world: dict) -> None:
    old = _add(db_session, world, KIND_CASH_IN, "1000", DAY - timedelta(days=5))
    access = _access(db_session, world["cashier"])
    assert cash_service.get_book(db_session, access, world["body"].id, DAY, DAY)[
        "opening"
    ] == Decimal("1000.00")

    cash_service.update_entry(
        db_session,
        access,
        old.id,
        entry_date=old.entry_date,
        kind=KIND_CASH_IN,
        amount=Decimal("1200"),
        comment=None,
        work_order_id=None,
        work_order_number=None,
        actor_user_id=world["cashier"].id,
        actor_name="Кассир Кассиров",
    )

    assert cash_service.get_book(db_session, access, world["body"].id, DAY, DAY)[
        "opening"
    ] == Decimal("1200.00")


def test_another_workshops_entries_are_separate(db_session: Session, world: dict) -> None:
    db_session.add(RoleTabVisibility(role="Админ", visible_tabs=["/cash"], all_departments=True))
    admin = _user(db_session, role="Админ")
    db_session.commit()
    _add(db_session, world, KIND_CASH_IN, "100")
    access = _access(db_session, admin)

    mech = cash_service.get_book(db_session, access, world["mech"].id, DAY, DAY)

    assert mech["closing"] == Decimal("0")
    assert mech["entries"] == []


# ---- create / edit / delete / audit -------------------------------------------


def test_create_records_who_when_and_writes_the_log(db_session: Session, world: dict) -> None:
    entry = _add(
        db_session,
        world,
        KIND_CASH_OUT,
        "26000.50",
        comment=" Ремонт компрессора ",
        work_order_number=" ПС00010483 ",
    )

    assert entry.amount == Decimal("26000.50")
    assert entry.comment == "Ремонт компрессора"
    assert entry.work_order_number == "ПС00010483"
    assert entry.created_by_name == "Кассир Кассиров"
    assert entry.created_at is not None
    assert entry.updated_at is None and entry.updated_by_name is None
    log = db_session.scalars(select(ScheduleAuditLog)).all()
    assert [(row.entity_type, row.entity_id, row.action) for row in log] == [
        ("cash_entry", entry.id, "create")
    ]
    assert log[0].changes["kind"]["new"] == "Расход НАЛ"
    assert log[0].changes["amount"]["new"] == "26000.50"


def test_amount_must_be_positive_and_kind_known(db_session: Session, world: dict) -> None:
    with pytest.raises(CashInvalid):
        _add(db_session, world, KIND_CASH_IN, "0")
    with pytest.raises(CashInvalid):
        _add(db_session, world, "bogus", "10")


def test_picking_a_work_order_copies_its_number(db_session: Session, world: dict) -> None:
    wo = WorkOrder(
        external_number="ПС00010505",
        source_system="alpha-auto",
        document_date=datetime(2026, 10, 9, tzinfo=UTC),
        amount=Decimal("1"),
    )
    db_session.add(wo)
    db_session.commit()

    entry = cash_service.create_entry(
        db_session,
        _access(db_session, world["cashier"]),
        workshop_id=world["body"].id,
        entry_date=DAY,
        kind=KIND_CASH_OUT,
        amount=Decimal("14000"),
        comment="генератор",
        work_order_id=wo.id,
        work_order_number="ignored typed text",
        actor_user_id=world["cashier"].id,
        actor_name="К",
    )

    assert entry.work_order_id == wo.id
    assert entry.work_order_number == "ПС00010505"


def test_update_changes_any_field_and_logs_only_the_diff(db_session: Session, world: dict) -> None:
    entry = _add(db_session, world, KIND_CASH_IN, "100", comment="было")
    access = _access(db_session, world["cashier"])
    editor = _user(db_session, full_name="Другой Кассир", workshop_id=world["body"].id)
    db_session.commit()

    updated = cash_service.update_entry(
        db_session,
        access,
        entry.id,
        entry_date=DAY + timedelta(days=1),
        kind=KIND_CARD_IN,
        amount=Decimal("250.5"),
        comment="стало",
        work_order_id=None,
        work_order_number="ПС1",
        actor_user_id=editor.id,
        actor_name="Другой Кассир",
    )

    assert updated is not None
    assert (updated.kind, updated.amount, updated.comment, updated.work_order_number) == (
        KIND_CARD_IN,
        Decimal("250.50"),
        "стало",
        "ПС1",
    )
    assert updated.created_by_name == "Кассир Кассиров"
    assert updated.updated_by_name == "Другой Кассир" and updated.updated_at is not None
    rows = db_session.scalars(
        select(ScheduleAuditLog).where(ScheduleAuditLog.action == "update")
    ).all()
    assert len(rows) == 1
    assert rows[0].actor_name == "Другой Кассир"
    assert set(rows[0].changes) == {"kind", "entry_date", "amount", "comment", "work_order_number"}
    assert rows[0].changes["amount"] == {"old": "100.00", "new": "250.50"}


def test_an_unchanged_save_writes_no_log_row(db_session: Session, world: dict) -> None:
    entry = _add(db_session, world, KIND_CASH_IN, "100")
    access = _access(db_session, world["cashier"])

    cash_service.update_entry(
        db_session,
        access,
        entry.id,
        entry_date=entry.entry_date,
        kind=entry.kind,
        amount=entry.amount,
        comment=entry.comment,
        work_order_id=None,
        work_order_number=None,
        actor_user_id=None,
        actor_name="x",
    )

    assert (
        db_session.scalars(
            select(ScheduleAuditLog).where(ScheduleAuditLog.action == "update")
        ).all()
        == []
    )


def test_zeroing_the_amount_deletes_the_entry_and_logs_it(db_session: Session, world: dict) -> None:
    entry = _add(db_session, world, KIND_CASH_IN, "100")
    access = _access(db_session, world["cashier"])

    result = cash_service.update_entry(
        db_session,
        access,
        entry.id,
        entry_date=DAY,
        kind=KIND_CASH_IN,
        amount=Decimal("0"),
        comment=None,
        work_order_id=None,
        work_order_number=None,
        actor_user_id=world["cashier"].id,
        actor_name="Кассир Кассиров",
    )

    assert result is None
    assert db_session.get(CashEntry, entry.id) is None
    actions = [
        r.action
        for r in db_session.scalars(select(ScheduleAuditLog).order_by(ScheduleAuditLog.created_at))
    ]
    assert actions == ["create", "delete"]


def test_unknown_entry_is_not_found(db_session: Session, world: dict) -> None:
    with pytest.raises(CashNotFound):
        cash_service.delete_entry(
            db_session,
            _access(db_session, world["cashier"]),
            uuid.uuid4(),
            actor_user_id=None,
            actor_name="x",
        )


# ---- locked period ------------------------------------------------------------


def _lock(db: Session, start: date, end: date) -> None:
    settings = cash_service.get_app_settings(db)
    settings.cash_lock_from = start
    settings.cash_lock_to = end
    db.commit()


def test_nothing_can_be_added_inside_the_locked_period(db_session: Session, world: dict) -> None:
    _lock(db_session, date(2026, 10, 1), date(2026, 10, 10))

    with pytest.raises(CashLocked):
        _add(db_session, world, KIND_CASH_IN, "10", date(2026, 10, 1))
    with pytest.raises(CashLocked):
        _add(
            db_session, world, KIND_CASH_IN, "10", date(2026, 10, 10)
        )  # the last day is locked too
    _add(db_session, world, KIND_CASH_IN, "10", date(2026, 10, 11))  # first day after
    _add(db_session, world, KIND_CASH_IN, "10", date(2026, 9, 30))  # last day before


def test_locked_entries_cannot_be_changed_deleted_or_moved(
    db_session: Session, world: dict
) -> None:
    inside = _add(db_session, world, KIND_CASH_IN, "100", date(2026, 10, 5))
    outside = _add(db_session, world, KIND_CASH_IN, "100", date(2026, 10, 20))
    access = _access(db_session, world["cashier"])
    _lock(db_session, date(2026, 10, 1), date(2026, 10, 10))
    common = dict(
        kind=KIND_CASH_IN,
        comment=None,
        work_order_id=None,
        work_order_number=None,
        actor_user_id=None,
        actor_name="x",
    )

    with pytest.raises(CashLocked):
        cash_service.update_entry(
            db_session,
            access,
            inside.id,
            entry_date=date(2026, 10, 5),
            amount=Decimal("1"),
            **common,
        )
    with pytest.raises(CashLocked):  # zeroing = deleting
        cash_service.update_entry(
            db_session,
            access,
            inside.id,
            entry_date=date(2026, 10, 5),
            amount=Decimal("0"),
            **common,
        )
    with pytest.raises(CashLocked):
        cash_service.delete_entry(db_session, access, inside.id, actor_user_id=None, actor_name="x")
    with pytest.raises(CashLocked):  # moving an open entry INTO the locked days
        cash_service.update_entry(
            db_session,
            access,
            outside.id,
            entry_date=date(2026, 10, 7),
            amount=Decimal("100"),
            **common,
        )
    assert db_session.get(CashEntry, inside.id) is not None
    assert db_session.get(CashEntry, outside.id).entry_date == date(2026, 10, 20)


def test_book_marks_locked_entries_and_reports_the_period(db_session: Session, world: dict) -> None:
    _add(db_session, world, KIND_CASH_IN, "100", date(2026, 10, 5))
    _add(db_session, world, KIND_CASH_IN, "100", date(2026, 10, 12))
    _lock(db_session, date(2026, 10, 1), date(2026, 10, 10))

    book = cash_service.get_book(
        db_session,
        _access(db_session, world["cashier"]),
        world["body"].id,
        date(2026, 10, 1),
        date(2026, 10, 31),
    )

    assert [e["locked"] for e in book["entries"]] == [True, False]
    assert (book["lock_from"], book["lock_to"]) == (date(2026, 10, 1), date(2026, 10, 10))


# ---- work-order drop-down ------------------------------------------------------


def _wo(number: str, dept: str, days_ago: int, **kw) -> WorkOrder:
    moment = datetime.now(UTC) + timedelta(hours=3) - timedelta(days=days_ago)
    return WorkOrder(
        external_number=number,
        source_system="alpha-auto",
        document_date=moment,
        created_date=moment,
        amount=Decimal("1"),
        department=dept,
        **kw,
    )


def test_work_order_list_is_the_workshops_last_100_days(db_session: Session, world: dict) -> None:
    db_session.add(
        WorkshopSourceDepartment(
            workshop_id=world["body"].id, source_department="Кузовной цех (Каховка)"
        )
    )
    db_session.add_all(
        [
            _wo(
                "МОЙ-1",
                "Кузовной цех (Каховка)",
                5,
                vehicle_description="Kia Optima",
                customer_name="Иванов",
            ),
            _wo("МОЙ-2", "Кузовной цех (Каховка)", 99),
            _wo("СТАРЫЙ", "Кузовной цех (Каховка)", 101),
            _wo("ЧУЖОЙ", "Слесарный цех", 5),
        ]
    )
    db_session.commit()
    access = _access(db_session, world["cashier"])

    everything = cash_service.search_work_orders(db_session, access, world["body"].id, "")
    by_text = cash_service.search_work_orders(db_session, access, world["body"].id, "optima")

    assert [w.external_number for w in everything] == ["МОЙ-1", "МОЙ-2"]  # newest first
    assert [w.external_number for w in by_text] == ["МОЙ-1"]


# ---- API ----------------------------------------------------------------------


def _headers(auth_headers: dict, user: User) -> dict:
    return {**auth_headers, "X-Actor-User-Id": str(user.id), "X-Actor-Name": quote(user.full_name)}


def test_api_full_cycle(client, db_session: Session, auth_headers, world: dict) -> None:
    headers = _headers(auth_headers, world["cashier"])
    body_id = str(world["body"].id)

    context = client.get("/api/v1/cash/context", headers=headers).json()
    assert [w["id"] for w in context["workshops"]] == [body_id]

    created = client.post(
        "/api/v1/cash/entries",
        headers=headers,
        json={
            "workshop_id": body_id,
            "entry_date": "2026-10-10",
            "kind": "cash_in",
            "amount": "1500.50",
            "comment": "Начальный остаток",
        },
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]

    book = client.get(
        "/api/v1/cash/book",
        params={"workshop_id": body_id, "date_from": "2026-10-10"},
        headers=headers,
    ).json()
    assert (book["opening"], book["closing"]) == ("0.00", "1500.50")
    assert book["entries"][0]["created_by_name"] == "Кассир Кассиров"

    edited = client.put(
        f"/api/v1/cash/entries/{entry_id}",
        headers=headers,
        json={"workshop_id": body_id, "entry_date": "2026-10-10", "kind": "cash_in", "amount": "0"},
    )
    assert edited.status_code == 200 and edited.json() == {"deleted": True, "entry": None}
    assert (
        client.get(
            "/api/v1/cash/book",
            params={"workshop_id": body_id, "date_from": "2026-10-10"},
            headers=headers,
        ).json()["entries"]
        == []
    )


def test_api_errors_map_to_http_codes(
    client, db_session: Session, auth_headers, world: dict
) -> None:
    headers = _headers(auth_headers, world["cashier"])
    other_id = str(world["other"].id)

    forbidden = client.get(
        "/api/v1/cash/book",
        params={"workshop_id": other_id, "date_from": "2026-10-10"},
        headers=headers,
    )
    assert forbidden.status_code == 403

    settings = cash_service.get_app_settings(db_session)
    settings.cash_lock_from, settings.cash_lock_to = date(2026, 10, 1), date(2026, 10, 31)
    db_session.commit()
    locked = client.post(
        "/api/v1/cash/entries",
        headers=headers,
        json={
            "workshop_id": str(world["body"].id),
            "entry_date": "2026-10-10",
            "kind": "cash_in",
            "amount": "10",
        },
    )
    assert locked.status_code == 423

    no_actor = client.get("/api/v1/cash/context", headers=auth_headers).json()
    assert no_actor["workshops"] == []


def test_audit_log_endpoint_filters_to_one_entry(
    client, db_session: Session, auth_headers, world: dict
) -> None:
    first = _add(db_session, world, KIND_CASH_IN, "100")
    _add(db_session, world, KIND_CASH_IN, "200")

    everything = client.get("/api/v1/settings/audit-log", headers=auth_headers).json()
    one = client.get(
        "/api/v1/settings/audit-log",
        params={"entity_type": "cash_entry", "entity_id": str(first.id)},
        headers=auth_headers,
    ).json()

    assert len(everything) == 2
    assert [row["entity_id"] for row in one] == [str(first.id)]


def test_lock_period_setting_needs_both_dates(client, auth_headers) -> None:
    base = {"daily_logout_time": "23:30"}

    only_from = client.put(
        "/api/v1/settings", headers=auth_headers, json={**base, "cash_lock_from": "2026-10-01"}
    )
    reversed_dates = client.put(
        "/api/v1/settings",
        headers=auth_headers,
        json={**base, "cash_lock_from": "2026-10-10", "cash_lock_to": "2026-10-01"},
    )
    ok = client.put(
        "/api/v1/settings",
        headers=auth_headers,
        json={**base, "cash_lock_from": "2026-10-01", "cash_lock_to": "2026-10-10"},
    )

    assert only_from.status_code == 422
    assert reversed_dates.status_code == 422
    assert ok.status_code == 200
    assert (ok.json()["cash_lock_from"], ok.json()["cash_lock_to"]) == ("2026-10-01", "2026-10-10")


def test_role_flag_roundtrips_through_admin_api(client, auth_headers) -> None:
    created = client.post(
        "/api/v1/settings/role-tab-visibility",
        headers=auth_headers,
        json={
            "role": "Бухгалтер",
            "visible_tabs": ["/cash", "/work-orders"],
            "all_departments": True,
        },
    )
    assert created.status_code == 201
    assert created.json()["all_departments"] is True
    row_id = created.json()["id"]

    updated = client.put(
        f"/api/v1/settings/role-tab-visibility/{row_id}",
        headers=auth_headers,
        json={"role": "Бухгалтер", "visible_tabs": ["/cash"], "all_departments": False},
    )
    assert updated.json()["all_departments"] is False


# ---- Корректировка кассы: today only without the right -------------------------


def _plain_cashier(db: Session, world: dict) -> User:
    user = _user(db, role="Сотрудник", workshop_id=world["body"].id)
    db.commit()
    return user


def test_without_the_right_only_today_can_be_written(db_session: Session, world: dict) -> None:
    user = _plain_cashier(db_session, world)
    access = _access(db_session, user)
    assert access.can_correct is False
    today = cash_service.today_msk()
    kwargs = dict(
        workshop_id=world["body"].id,
        kind=KIND_CASH_IN,
        amount=Decimal("10"),
        comment=None,
        work_order_id=None,
        work_order_number=None,
        actor_user_id=user.id,
        actor_name="Сотрудник",
    )

    entry = cash_service.create_entry(db_session, access, entry_date=today, **kwargs)
    with pytest.raises(CashForbidden):
        cash_service.create_entry(
            db_session, access, entry_date=today - timedelta(days=1), **kwargs
        )
    with pytest.raises(CashForbidden):
        cash_service.create_entry(
            db_session, access, entry_date=today + timedelta(days=1), **kwargs
        )
    # moving today's entry to another day is refused too, and so is deleting
    # an old one
    with pytest.raises(CashForbidden):
        cash_service.update_entry(
            db_session,
            access,
            entry.id,
            entry_date=today - timedelta(days=2),
            **{k: v for k, v in kwargs.items() if k != "workshop_id"},
        )
    old = _add(db_session, world, KIND_CASH_IN, "5", today - timedelta(days=3))
    with pytest.raises(CashForbidden):
        cash_service.delete_entry(
            db_session, access, old.id, actor_user_id=user.id, actor_name="Сотрудник"
        )


def test_with_the_right_any_day_can_be_written_and_context_says_so(
    db_session: Session, world: dict
) -> None:
    access = _access(db_session, world["cashier"])
    assert access.can_correct is True
    context = cash_service.get_context(db_session, world["cashier"].id)
    assert context["can_correct"] is True
    assert context["today"] == cash_service.today_msk()
    _add(db_session, world, KIND_CASH_IN, "5", DAY)


# ---- search by work-order number ----------------------------------------------


def test_search_finds_entries_earliest_first_and_stays_in_the_desk(
    db_session: Session, world: dict
) -> None:
    late = _add(
        db_session,
        world,
        KIND_CASH_IN,
        "1",
        DAY + timedelta(days=5),
        work_order_number="ПС00010503",
    )
    early = _add(db_session, world, KIND_CARD_IN, "2", DAY, work_order_number="ПС00010503")
    _add(db_session, world, KIND_CASH_IN, "3", DAY, work_order_number="ПС00010999")
    db_session.add(
        CashEntry(
            workshop_id=world["mech"].id,
            entry_date=DAY,
            kind=KIND_CASH_IN,
            amount=Decimal("4"),
            work_order_number="ПС00010503",
            created_by_name="x",
        )
    )
    db_session.commit()
    access = _access(db_session, world["cashier"])

    found = cash_service.search_entries(db_session, access, world["body"].id, "10503")

    assert [e.id for e in found] == [early.id, late.id]

    # the same field also finds entries by comment text (any case)
    commented = _add(
        db_session,
        world,
        KIND_CASH_OUT,
        "9",
        DAY + timedelta(days=1),
        comment="Уборщица за октябрь",
    )
    by_comment = cash_service.search_entries(db_session, access, world["body"].id, "убОРщ")
    assert [e.id for e in by_comment] == [commented.id]
    assert cash_service.search_entries(db_session, access, world["body"].id, "  ") == []
    with pytest.raises(CashForbidden):
        cash_service.search_entries(db_session, access, world["other"].id, "10503")
