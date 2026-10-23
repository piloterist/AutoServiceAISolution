"""Tests for services/conversion_service.py - Телефония -> "Конверсия": each
inbound call of a period matched to the first work order created after it
on the same phone, plus the "Существующий" flag."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.call_record import CallRecord
from app.models.employee import Employee
from app.models.work_order import WorkOrder
from app.services import conversion_service

DAY = date(2026, 10, 10)
PHONE = "9990000001"


def _call(
    db: Session,
    *,
    external_id: str,
    day: int = 10,
    hour_msk: int = 12,
    call_type: str = "IN",
    client: str = PHONE,
    talk_sec: int = 0,
) -> CallRecord:
    call = CallRecord(
        id=uuid.uuid4(),
        provider="zeon",
        external_id=external_id,
        call_date=date(2026, 10, day),
        # MSK is UTC+3.
        occurred_at=datetime(2026, 10, day, hour_msk - 3, 0, tzinfo=UTC),
        call_type=call_type,
        client=client,
        line="pan",
        operator="302",
        wait_sec=10,
        talk_sec=talk_sec,
        answered=talk_sec > 0,
    )
    db.add(call)
    return call


def _wo(number: str, created: datetime, phone: str | None = "+7 (999) 000-00-01", **kw):
    return WorkOrder(
        external_number=number,
        source_system="alpha-auto",
        document_date=created,
        created_date=created,
        amount=Decimal("1000.00"),
        phone=phone,
        **kw,
    )


def _times(group) -> list[str]:
    return [call.time[11:13] for call in group.calls]


def test_only_inbound_calls_of_the_period_are_listed(db_session: Session) -> None:
    _call(db_session, external_id="in", call_type="IN")
    _call(db_session, external_id="out", call_type="OUT", talk_sec=20)
    _call(db_session, external_id="other-day", day=20)
    db_session.commit()

    groups = conversion_service.list_conversion(db_session, DAY, DAY)

    assert [len(g.calls) for g in groups] == [1]
    assert groups[0].calls[0].direction == "in"


def test_many_calls_leading_to_one_work_order_form_one_row(db_session: Session) -> None:
    for i, hour in enumerate((9, 11, 14)):
        _call(db_session, external_id=f"c{i}", hour_msk=hour)
    db_session.add(_wo("ЗН-1", datetime(2026, 10, 11, 9, 0, tzinfo=UTC)))
    db_session.commit()

    (group,) = conversion_service.list_conversion(db_session, DAY, DAY)

    assert group.work_order_number == "ЗН-1"
    assert _times(group) == ["09", "11", "14"]  # oldest first
    assert group.is_existing is False


def test_calls_without_a_later_work_order_form_one_row_without_work_order(
    db_session: Session,
) -> None:
    for i, hour in enumerate((9, 11)):
        _call(db_session, external_id=f"c{i}", hour_msk=hour)
    db_session.commit()

    (group,) = conversion_service.list_conversion(db_session, DAY, DAY)

    assert group.work_order_number is None
    assert group.work_order_id is None
    assert len(group.calls) == 2


def test_phone_with_several_work_orders_gets_a_row_per_work_order(db_session: Session) -> None:
    # 09:00 and 10:00 MSK calls -> ЗН-A (created 12:00 MSK); 15:00 and 18:00
    # calls -> ЗН-B (created 16:30 MSK for the 15:00 one? no: 15:00 -> ЗН-B).
    for i, hour in enumerate((9, 10, 15, 18)):
        _call(db_session, external_id=f"c{i}", hour_msk=hour)
    db_session.add(_wo("ЗН-A", datetime(2026, 10, 10, 9, 0, tzinfo=UTC)))  # 12:00 MSK
    db_session.add(_wo("ЗН-B", datetime(2026, 10, 10, 15, 30, tzinfo=UTC)))  # 18:30 MSK
    db_session.commit()

    groups = conversion_service.list_conversion(db_session, DAY, DAY)

    by_number = {g.work_order_number: g for g in groups}
    assert set(by_number) == {"ЗН-A", "ЗН-B"}
    assert _times(by_number["ЗН-A"]) == ["09", "10"]
    assert _times(by_number["ЗН-B"]) == ["15", "18"]
    assert by_number["ЗН-A"].is_existing is False
    # ЗН-B's first call (15:00) comes after ЗН-A was created (12:00).
    assert by_number["ЗН-B"].is_existing is True
    # Newest first by each group's first call.
    assert [g.work_order_number for g in groups] == ["ЗН-B", "ЗН-A"]


def test_calls_after_the_last_work_order_form_a_separate_row(db_session: Session) -> None:
    _call(db_session, external_id="before", hour_msk=9)
    _call(db_session, external_id="after", hour_msk=18)
    db_session.add(_wo("ЗН", datetime(2026, 10, 10, 12, 0, tzinfo=UTC)))  # 15:00 MSK
    db_session.commit()

    groups = conversion_service.list_conversion(db_session, DAY, DAY)

    by_number = {g.work_order_number: g for g in groups}
    assert _times(by_number["ЗН"]) == ["09"]
    assert _times(by_number[None]) == ["18"]
    assert by_number[None].is_existing is True


def test_work_order_before_call_makes_client_existing_but_is_not_the_match(
    db_session: Session,
) -> None:
    _call(db_session, external_id="c1", hour_msk=12)
    db_session.add(_wo("OLD", datetime(2025, 3, 1, 9, 0, tzinfo=UTC), status="Закрыт"))
    db_session.commit()

    (group,) = conversion_service.list_conversion(db_session, DAY, DAY)

    assert group.is_existing is True
    assert group.work_order_number is None


def test_existing_client_with_a_new_work_order_after_the_call(db_session: Session) -> None:
    _call(db_session, external_id="c1", hour_msk=12)
    db_session.add(_wo("OLD", datetime(2025, 3, 1, 9, 0, tzinfo=UTC)))
    db_session.add(_wo("NEW", datetime(2026, 10, 10, 15, 0, tzinfo=UTC)))
    db_session.commit()

    (group,) = conversion_service.list_conversion(db_session, DAY, DAY)

    assert group.is_existing is True
    assert group.work_order_number == "NEW"


def test_different_phones_never_share_a_group(db_session: Session) -> None:
    _call(db_session, external_id="a", client="9990000001")
    _call(db_session, external_id="b", client="9990000002")
    db_session.add(_wo("ЗН", datetime(2026, 10, 12, 9, 0, tzinfo=UTC), phone="+7 999 000 00 01"))
    db_session.commit()

    groups = {g.client: g for g in conversion_service.list_conversion(db_session, DAY, DAY)}

    assert groups["9990000001"].work_order_number == "ЗН"
    assert groups["9990000002"].work_order_number is None


def test_phone_formats_are_normalized_and_other_numbers_ignored(db_session: Session) -> None:
    _call(db_session, external_id="c1", hour_msk=12)
    db_session.add(_wo("MATCH", datetime(2026, 10, 11, 9, 0, tzinfo=UTC), phone="89990000001"))
    db_session.add(_wo("OTHER", datetime(2026, 10, 11, 9, 0, tzinfo=UTC), phone="+7 999 000 00 02"))
    db_session.add(_wo("NOPHONE", datetime(2026, 10, 11, 9, 0, tzinfo=UTC), phone=None))
    db_session.commit()

    (group,) = conversion_service.list_conversion(db_session, DAY, DAY)

    assert group.work_order_number == "MATCH"


def test_uses_created_date_not_the_import_time(db_session: Session) -> None:
    """created_at (our import time) is always "now" in this test; only
    created_date says the order really existed long before the call."""
    _call(db_session, external_id="c1", hour_msk=12)
    db_session.add(_wo("OLD", datetime(2024, 5, 1, 9, 0, tzinfo=UTC)))
    db_session.commit()

    (group,) = conversion_service.list_conversion(db_session, DAY, DAY)

    assert group.is_existing is True
    assert group.work_order_number is None


def test_employee_phone_is_excluded(db_session: Session) -> None:
    _call(db_session, external_id="c1")
    db_session.add(Employee(full_name="Сотрудник", specialty="Менеджер", phone="+7 999 000-00-01"))
    db_session.commit()

    assert conversion_service.list_conversion(db_session, DAY, DAY) == []
