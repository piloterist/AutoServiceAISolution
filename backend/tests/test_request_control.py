"""Контроль заявок на ремонт (services/request_control_service.py и /api/v1/repair-requests):
попытки из телефонии и ручные, просрочка первого/второго звонка, дисквалификация, цех."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings
from app.models.call_record import CallRecord
from app.models.department import Department
from app.models.role_tab_visibility import RoleTabVisibility
from app.models.user import User
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop
from app.models.workshop_source_department import WorkshopSourceDepartment
from app.services import request_control_service as control
from app.services.settings_service import get_app_settings

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
PHONE = "9001112233"
RAW_PHONE = "+7 (900) 111-22-33"


def _enable(db: Session, **kw) -> AppSettings:
    settings = get_app_settings(db)  # the row may already exist (created on first read)
    settings.request_control_enabled = True
    for name, value in kw.items():
        setattr(settings, name, value)
    db.commit()
    return settings


def _request(
    db: Session,
    *,
    age_days: float,
    number: str | None = None,
    phone: str | None = RAW_PHONE,
    department: str | None = "Кузовной цех (Каховка)",
    **kw,
) -> WorkOrder:
    created = NOW - timedelta(days=age_days)
    request = WorkOrder(
        external_number=number or f"ЭП{uuid.uuid4().hex[:8]}",
        source_system="alpha-auto-repair_request",
        doc_type="repair_request",
        document_date=created,
        created_date=created,
        phone=phone,
        department=department,
        customer_name="Клиент",
        amount=Decimal("0"),
        **kw,
    )
    db.add(request)
    db.commit()
    return request


def _call(
    db: Session,
    *,
    at: datetime,
    phone: str = PHONE,
    call_type: str = "OUT",
    talk_sec: int = 60,
    operator: str = "302",
) -> CallRecord:
    call = CallRecord(
        provider="zeon",
        external_id=str(uuid.uuid4()),
        call_date=at.date(),
        occurred_at=at,
        call_type=call_type,
        client=phone,
        operator=operator,
        wait_sec=5,
        talk_sec=talk_sec,
        answered=talk_sec > 0,
    )
    db.add(call)
    db.commit()
    return call


def _overdue(db: Session, **kw) -> dict[uuid.UUID, str]:
    return {s.request.id: s.overdue for s in control.overdue_states(db, now=NOW, **kw)}


# ---- просрочка -----------------------------------------------------------------


def test_nothing_is_overdue_while_control_is_off(db_session) -> None:
    get_app_settings(db_session)  # defaults: control is off
    _request(db_session, age_days=5)
    assert control.overdue_states(db_session, now=NOW) == []


def test_first_call_is_overdue_after_the_first_deadline(db_session) -> None:
    _enable(db_session)  # 3 / 7 / 20 с
    fresh = _request(db_session, age_days=2)
    late = _request(db_session, age_days=4)
    result = _overdue(db_session)
    assert fresh.id not in result
    assert result[late.id] == "first"


def test_a_missed_short_or_incoming_call_is_not_an_attempt(db_session) -> None:
    _enable(db_session)
    request = _request(db_session, age_days=4)
    _call(db_session, at=NOW - timedelta(days=3), talk_sec=0)  # недозвон
    _call(db_session, at=NOW - timedelta(days=3, hours=1), talk_sec=19)  # короче порога
    _call(db_session, at=NOW - timedelta(days=2), call_type="IN", talk_sec=120)  # входящий
    state = control.get_state(db_session, request.id, now=NOW)
    assert state.attempts_count == 0
    assert state.missed_calls == 2  # недозвон и короткий; входящий не считается вовсе
    assert state.overdue == "first"


def test_a_real_outgoing_call_counts_whatever_line_or_operator(db_session) -> None:
    _enable(db_session)
    request = _request(db_session, age_days=4)
    _call(db_session, at=NOW - timedelta(days=3), talk_sec=20, operator="999")
    state = control.get_state(db_session, request.id, now=NOW)
    assert state.attempts_count == 1
    assert state.overdue is None  # первый звонок есть; срок второго (7 дн.) ещё не вышел


def test_a_call_before_the_request_was_created_does_not_count(db_session) -> None:
    _enable(db_session)
    request = _request(db_session, age_days=4)
    _call(db_session, at=NOW - timedelta(days=5))
    assert control.get_state(db_session, request.id, now=NOW).attempts_count == 0


def test_min_talk_seconds_is_a_setting(db_session) -> None:
    _enable(db_session, request_min_talk_sec=45)
    request = _request(db_session, age_days=4)
    _call(db_session, at=NOW - timedelta(days=3), talk_sec=30)
    assert control.get_state(db_session, request.id, now=NOW).attempts_count == 0


def test_second_call_is_overdue_after_the_second_deadline(db_session) -> None:
    _enable(db_session)
    request = _request(db_session, age_days=8)
    _call(db_session, at=NOW - timedelta(days=6))
    assert _overdue(db_session)[request.id] == "second"


def test_two_calls_on_one_day_are_one_attempt(db_session) -> None:
    _enable(db_session)
    request = _request(db_session, age_days=8)
    _call(db_session, at=NOW - timedelta(days=6, hours=3))
    _call(db_session, at=NOW - timedelta(days=6, hours=1))
    state = control.get_state(db_session, request.id, now=NOW)
    assert state.attempts_count == 1
    assert state.overdue == "second"


def test_two_attempts_on_different_days_clear_the_overdue(db_session) -> None:
    _enable(db_session)
    request = _request(db_session, age_days=8)
    _call(db_session, at=NOW - timedelta(days=6))
    _call(db_session, at=NOW - timedelta(days=2))
    assert control.get_state(db_session, request.id, now=NOW).overdue is None
    assert request.id not in _overdue(db_session)


def test_deadlines_come_from_the_settings(db_session) -> None:
    _enable(db_session, request_first_call_days=1, request_second_call_days=2)
    request = _request(db_session, age_days=1.5)
    assert _overdue(db_session)[request.id] == "first"


def test_closed_requests_are_never_overdue(db_session) -> None:
    _enable(db_session)
    converted = _request(db_session, age_days=5, linked_work_orders="ЭПЭП0001")
    disqualified = _request(db_session, age_days=5, request_disqualified_at=NOW)
    expired = _request(db_session, age_days=31)
    result = _overdue(db_session)
    assert not {converted.id, disqualified.id, expired.id} & set(result)
    assert control.get_state(db_session, expired.id, now=NOW).status == "expired"
    assert control.get_state(db_session, converted.id, now=NOW).status == "converted"


def test_an_ordinary_work_order_is_not_a_request(db_session) -> None:
    _enable(db_session)
    created = NOW - timedelta(days=5)
    db_session.add(
        WorkOrder(
            external_number="ЗН-1",
            document_date=created,
            created_date=created,
            phone=RAW_PHONE,
            amount=Decimal("1"),
        )
    )
    db_session.commit()
    assert _overdue(db_session) == {}


# ---- ручные попытки -----------------------------------------------------------


def test_manual_attempt_needs_a_comment_and_counts(db_session) -> None:
    _enable(db_session)
    request = _request(db_session, age_days=4)
    with pytest.raises(control.RequestInvalid):
        control.add_manual_attempt(
            db_session, request.id, user_id=None, user_name="Мастер", comment="  ", now=NOW
        )
    state = control.add_manual_attempt(
        db_session,
        request.id,
        user_id=None,
        user_name="Мастер",
        comment="Написал в WhatsApp, ответил",
        now=NOW,
    )
    assert state.attempts_count == 1
    assert state.attempts[0].kind == "manual"
    assert state.attempts[0].comment == "Написал в WhatsApp, ответил"
    assert state.overdue is None


def test_manual_attempt_cannot_be_in_the_future_or_on_a_closed_request(db_session) -> None:
    _enable(db_session)
    request = _request(db_session, age_days=4)
    with pytest.raises(control.RequestInvalid):
        control.add_manual_attempt(
            db_session,
            request.id,
            user_id=None,
            user_name="М",
            comment="x",
            attempted_at=NOW + timedelta(days=1),
            now=NOW,
        )
    closed = _request(db_session, age_days=4, linked_work_orders="ЭПЭП0002")
    with pytest.raises(control.RequestNotOpen):
        control.add_manual_attempt(
            db_session, closed.id, user_id=None, user_name="М", comment="x", now=NOW
        )


# ---- дисквалификация ----------------------------------------------------------


def _user(db: Session, role: str, **kw) -> User:
    user = User(
        full_name=f"{role} Тестов",
        login=f"u-{uuid.uuid4().hex[:8]}",
        password_hash="x",
        role=role,
        **kw,
    )
    db.add(user)
    db.commit()
    return user


def _two_attempts(db: Session, request: WorkOrder) -> None:
    _call(db, at=NOW - timedelta(days=3))
    _call(db, at=NOW - timedelta(days=1))


def test_disqualify_needs_two_attempts(db_session) -> None:
    _enable(db_session)
    advisor = _user(db_session, "Мастер приёмщик")
    request = _request(db_session, age_days=5)
    with pytest.raises(control.RequestForbidden):
        control.disqualify(
            db_session,
            request.id,
            user_id=advisor.id,
            user_name=advisor.full_name,
            reason="Отказ клиента",
            comment=None,
            now=NOW,
        )
    _call(db_session, at=NOW - timedelta(days=3))
    with pytest.raises(control.RequestForbidden):  # одна попытка - мало
        control.disqualify(
            db_session,
            request.id,
            user_id=advisor.id,
            user_name=advisor.full_name,
            reason="Отказ клиента",
            comment=None,
            now=NOW,
        )
    _call(db_session, at=NOW - timedelta(days=1))
    state = control.disqualify(
        db_session,
        request.id,
        user_id=advisor.id,
        user_name=advisor.full_name,
        reason="Отказ клиента",
        comment=None,
        now=NOW,
    )
    assert state.status == "disqualified"
    assert state.request.request_disqualified_by == advisor.full_name
    assert request.id not in _overdue(db_session)


def test_disqualify_without_attempts_needs_the_role_right(db_session) -> None:
    _enable(db_session)
    db_session.add(
        RoleTabVisibility(
            role="Управляющий", visible_tabs=["/errors"], request_disqualify_unchecked=True
        )
    )
    db_session.commit()
    manager = _user(db_session, "Управляющий")
    admin = _user(db_session, "Админ")  # право есть всегда
    advisor = _user(db_session, "Мастер приёмщик")
    first, second, third = (_request(db_session, age_days=5) for _ in range(3))

    for request, user in ((first, manager), (second, admin)):
        state = control.disqualify(
            db_session,
            request.id,
            user_id=user.id,
            user_name=user.full_name,
            reason="Ошибочная заявка",
            comment=None,
            now=NOW,
        )
        assert state.status == "disqualified"
    with pytest.raises(control.RequestForbidden):
        control.disqualify(
            db_session,
            third.id,
            user_id=advisor.id,
            user_name="М",
            reason="Ошибочная заявка",
            comment=None,
            now=NOW,
        )


def test_disqualify_validates_the_reason_and_the_state(db_session) -> None:
    _enable(db_session)
    admin = _user(db_session, "Админ")
    request = _request(db_session, age_days=5)

    def run(reason: str, comment: str | None = None):
        return control.disqualify(
            db_session,
            request.id,
            user_id=admin.id,
            user_name="А",
            reason=reason,
            comment=comment,
            now=NOW,
        )

    with pytest.raises(control.RequestInvalid):
        run("Потому что")
    with pytest.raises(control.RequestInvalid):
        run("Другое")  # без комментария
    run("Другое", "Клиент продал машину")
    with pytest.raises(control.RequestNotOpen):
        run("Дорого")  # уже дисквалифицирована


# ---- цех пользователя ---------------------------------------------------------


def test_scope_follows_the_users_workshop(db_session) -> None:
    _enable(db_session)
    kahovka = Department(name="Каховка")
    solntsevo = Department(name="Солнцево")
    db_session.add_all([kahovka, solntsevo])
    db_session.flush()
    workshops = {}
    for dept in (kahovka, solntsevo):
        workshop = Workshop(
            department_id=dept.id,
            workshop_type="Кузовной",
            posts_count=1,
            start_time="08:00:00",
            end_time="20:00:00",
            working_days=[0],
        )
        db_session.add(workshop)
        db_session.flush()
        workshops[dept.name] = workshop
        db_session.add(
            WorkshopSourceDepartment(
                workshop_id=workshop.id, source_department=f"Кузовной цех ({dept.name})"
            )
        )
    db_session.commit()
    kah = _request(db_session, age_days=4, department="Кузовной цех (Каховка)")
    sol = _request(db_session, age_days=4, department="Кузовной цех (Солнцево)")

    advisor = _user(db_session, "Мастер приёмщик", workshop_id=workshops["Каховка"].id)
    manager = _user(db_session, "Управляющий")  # ни цеха, ни подразделения - видит все

    mine = control.departments_for_user(db_session, advisor.id)
    assert mine == ["Кузовной цех (Каховка)"]
    assert set(_overdue(db_session, departments=mine)) == {kah.id}
    assert control.departments_for_user(db_session, manager.id) is None
    assert set(_overdue(db_session, departments=None)) == {kah.id, sol.id}


def test_scope_follows_the_planner_workshop(db_session) -> None:
    """Колокольчик слесарного планировщика не показывает заявки кузовного цеха того же филиала."""
    _enable(db_session)
    kahovka = Department(name="Каховка")
    db_session.add(kahovka)
    db_session.flush()
    shops = {}
    for kind in ("Кузовной", "Слесарный"):
        shop = Workshop(
            department_id=kahovka.id,
            workshop_type=kind,
            posts_count=1,
            start_time="08:00:00",
            end_time="20:00:00",
            working_days=[0],
        )
        db_session.add(shop)
        db_session.flush()
        shops[kind] = shop
    db_session.add(
        WorkshopSourceDepartment(
            workshop_id=shops["Кузовной"].id, source_department="Кузовной цех (Каховка)"
        )
    )
    db_session.commit()
    body = _request(db_session, age_days=4, department="Кузовной цех (Каховка)")
    manager = _user(db_session, "Управляющий")

    body_scope = control.departments_for_workshop(db_session, manager.id, shops["Кузовной"].id)
    assert set(_overdue(db_session, departments=body_scope)) == {body.id}
    # у слесарного цеха нет привязанных подразделений - заявок в нём нет
    locksmith_scope = control.departments_for_workshop(
        db_session, manager.id, shops["Слесарный"].id
    )
    assert locksmith_scope == []
    assert _overdue(db_session, departments=locksmith_scope) == {}


# ---- API ----------------------------------------------------------------------


def _actor(user: User) -> dict[str, str]:
    return {"X-Actor-User-Id": str(user.id), "X-Actor-Name": "Tester"}


def test_overdue_endpoint_and_the_filtered_list(client, db_session, auth_headers) -> None:
    now = datetime.now(UTC)
    _enable(db_session)
    created = now - timedelta(days=4)
    late = WorkOrder(
        external_number="ЭП-ПРОСРОЧЕНА",
        source_system="alpha-auto-repair_request",
        doc_type="repair_request",
        document_date=created,
        created_date=created,
        phone=RAW_PHONE,
        department="Кузовной цех (Каховка)",
        amount=Decimal("0"),
    )
    fine = WorkOrder(
        external_number="ЭП-СВЕЖАЯ",
        source_system="alpha-auto-repair_request",
        doc_type="repair_request",
        document_date=now - timedelta(hours=5),
        created_date=now - timedelta(hours=5),
        phone="9002223344",
        amount=Decimal("0"),
    )
    db_session.add_all([late, fine])
    db_session.commit()

    overdue = client.get("/api/v1/repair-requests/overdue?scope=all", headers=auth_headers).json()
    assert overdue["enabled"] is True
    assert overdue["first_count"] == 1 and overdue["second_count"] == 0
    assert [item["external_number"] for item in overdue["items"]] == ["ЭП-ПРОСРОЧЕНА"]

    listed = client.get("/api/v1/work-orders?include_requests=true", headers=auth_headers).json()[
        "items"
    ]
    by_number = {item["external_number"]: item for item in listed}
    assert by_number["ЭП-ПРОСРОЧЕНА"]["request_issue"] == "first"
    assert by_number["ЭП-СВЕЖАЯ"]["request_issue"] is None

    only = client.get("/api/v1/work-orders?only_request_issues=true", headers=auth_headers).json()
    assert [item["external_number"] for item in only["items"]] == ["ЭП-ПРОСРОЧЕНА"]
    assert only["total"] == 1


def test_control_endpoints_attempt_and_disqualify(client, db_session, auth_headers) -> None:
    now = datetime.now(UTC)
    _enable(db_session)
    advisor = _user(db_session, "Мастер приёмщик")
    created = now - timedelta(days=5)
    request = WorkOrder(
        external_number="ЭП-API",
        source_system="alpha-auto-repair_request",
        doc_type="repair_request",
        document_date=created,
        created_date=created,
        phone=RAW_PHONE,
        amount=Decimal("0"),
    )
    db_session.add(request)
    db_session.commit()
    headers = {**auth_headers, **_actor(advisor)}
    base = f"/api/v1/repair-requests/{request.id}"

    card = client.get(f"{base}/control", headers=headers).json()
    assert card["status"] == "open" and card["overdue"] == "first"
    assert card["can_disqualify"] is False
    assert "Отказ клиента" in card["reasons"]

    assert (
        client.post(f"{base}/attempts", json={"comment": " "}, headers=headers).status_code == 422
    )
    marked = client.post(
        f"{base}/attempts", json={"comment": "Написал в мессенджер"}, headers=headers
    )
    assert marked.status_code == 200
    assert marked.json()["attempts_count"] == 1 and marked.json()["overdue"] is None

    refused = client.post(f"{base}/disqualify", json={"reason": "Дорого"}, headers=headers)
    assert refused.status_code == 403

    admin = _user(db_session, "Админ")
    done = client.post(
        f"{base}/disqualify",
        json={"reason": "Дорого"},
        headers={**auth_headers, **_actor(admin)},
    )
    assert done.status_code == 200
    assert done.json()["status"] == "disqualified"
    assert done.json()["disqualify_reason"] == "Дорого"
    assert client.get(f"{base}/control", headers=headers).json()["can_disqualify"] is False
    assert (
        client.post(f"{base}/disqualify", json={"reason": "Дорого"}, headers=headers).status_code
        == 409
    )
    assert (
        client.get(f"/api/v1/repair-requests/{uuid.uuid4()}/control", headers=headers).status_code
        == 404
    )
