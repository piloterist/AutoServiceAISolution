"""Tests for services/conversion_service.py - Телефония -> "Конверсия": each
inbound call of a period matched to the first work order created after it
on the same phone, plus the "Существующий" flag."""

import uuid
from datetime import UTC, date, datetime, timedelta
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
    topic_tag: str | None = None,
    minute_msk: int = 0,
    workshop_id: uuid.UUID | None = None,
) -> CallRecord:
    call = CallRecord(
        id=uuid.uuid4(),
        provider="zeon",
        external_id=external_id,
        call_date=date(2026, 10, day),
        # MSK is UTC+3.
        occurred_at=datetime(2026, 10, day, hour_msk - 3, minute_msk, tzinfo=UTC),
        call_type=call_type,
        client=client,
        line="pan",
        operator="302",
        wait_sec=10,
        talk_sec=talk_sec,
        answered=talk_sec > 0,
        topic_tag=topic_tag,
        workshop_id=workshop_id,
    )
    db.add(call)
    return call


def _stored(real_utc: datetime | None) -> datetime | None:
    """How the importer stores a work-order date: 1C's Moscow clock reading,
    as if it were UTC - i.e. 3 hours later than the real instant."""
    return None if real_utc is None else real_utc + timedelta(hours=3)


def _wo(number: str, created: datetime, phone: str | None = "+7 (999) 000-00-01", **kw):
    """`created` (and closed_date/end_date in `kw`) are REAL instants here."""
    for key in ("closed_date", "end_date"):
        if key in kw:
            kw[key] = _stored(kw[key])
    return WorkOrder(
        external_number=number,
        source_system="alpha-auto",
        document_date=_stored(created),
        created_date=_stored(created),
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


def test_our_callback_after_missed_calls_is_part_of_the_group(db_session: Session) -> None:
    for i, hour in enumerate((9, 10, 11)):
        _call(db_session, external_id=f"miss{i}", hour_msk=hour)
    _call(db_session, external_id="cb", hour_msk=12, call_type="OUT", talk_sec=40)
    # An outbound call with no preceding miss is not a callback - not listed.
    _call(db_session, external_id="cold", client="9990000009", call_type="OUT", talk_sec=40)
    db_session.commit()

    groups = conversion_service.list_conversion(db_session, DAY, DAY)

    (group,) = groups
    assert group.client == PHONE
    assert [c.direction for c in group.calls] == ["in", "in", "in", "out"]
    assert group.calls[-1].role == "callback"


# ---- Конверсия для страницы Аналитика ---------------------------------------

TOPIC = "Запись на ремонт"


def test_summary_counts_unique_new_numbers_with_a_talk_and_a_topic(db_session: Session) -> None:
    from app.models.call_record import TOPIC_UNDETERMINED

    # A: three missed calls, then our callback with a real talk -> ONE number.
    for i, hour in enumerate((9, 10, 11)):
        _call(db_session, external_id=f"a{i}", hour_msk=hour, client="9990000001")
    _call(
        db_session,
        external_id="a-cb",
        hour_msk=12,
        call_type="OUT",
        client="9990000001",
        talk_sec=30,
        topic_tag=TOPIC,
    )
    # B: talked with a topic, but already had a work order before -> existing.
    _call(db_session, external_id="b", client="9990000002", talk_sec=40, topic_tag=TOPIC)
    # C: talked, topic "not defined" (advert / robot) -> dropped.
    _call(
        db_session, external_id="c", client="9990000003", talk_sec=40, topic_tag=TOPIC_UNDETERMINED
    )
    # D: only missed calls -> dropped.
    _call(db_session, external_id="d", client="9990000004")
    # E: our own outbound call (no miss before it) -> not a callback, dropped.
    _call(
        db_session,
        external_id="e",
        client="9990000005",
        call_type="OUT",
        talk_sec=40,
        topic_tag=TOPIC,
    )
    # F: new number with a talk and topic, never got a work order.
    _call(db_session, external_id="f", client="9990000006", talk_sec=40, topic_tag=TOPIC)
    # G: missed, then called back twice and talked both times -> still ONE.
    _call(db_session, external_id="g0", hour_msk=9, client="9990000007")
    _call(
        db_session,
        external_id="g1",
        hour_msk=10,
        call_type="OUT",
        client="9990000007",
        talk_sec=20,
        topic_tag=TOPIC,
    )
    _call(
        db_session,
        external_id="g2",
        hour_msk=11,
        call_type="OUT",
        client="9990000007",
        talk_sec=25,
        topic_tag=TOPIC,
    )
    # H: talked for under 5 seconds -> not a conversation.
    _call(db_session, external_id="h", client="9990000008", talk_sec=3, topic_tag=TOPIC)

    db_session.add(
        _wo(
            "B-OLD",
            datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 02",
            status="Закрыт",
        )
    )
    # A got a work order after the callback (15:00 MSK on the day).
    db_session.add(
        _wo("A-NEW", datetime(2026, 10, 10, 12, 0, tzinfo=UTC), phone="+7 999 000 00 01")
    )
    # An order from someone who never called (still counts in the total).
    db_session.add(
        _wo("WALK-IN", datetime(2026, 10, 10, 8, 0, tzinfo=UTC), phone="+7 999 111 11 11")
    )
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.talk_phones == 5  # A, B, C, F, G
    assert summary.topic_phones == 4  # A, B, F, G
    assert summary.new_clients == 3  # A, F, G (B already a client)
    assert summary.converted_new_clients == 1  # A
    assert summary.work_orders_new_clients == 1
    assert summary.work_orders_total == 2  # A-NEW + WALK-IN (B-OLD is outside)
    assert summary.conversion_pct == 33.3
    assert summary.calls_total == 13


def test_summary_without_new_clients_has_no_percentage(db_session: Session) -> None:
    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.new_clients == 0
    assert summary.conversion_pct is None


def test_summary_work_order_must_come_after_the_conversation(db_session: Session) -> None:
    _call(
        db_session, external_id="a", hour_msk=15, client="9990000001", talk_sec=40, topic_tag=TOPIC
    )
    # Created at 09:00 MSK - before the 15:00 call -> that makes the number
    # an existing client, so it isn't new at all.
    db_session.add(
        _wo("BEFORE", datetime(2026, 10, 10, 6, 0, tzinfo=UTC), phone="+7 999 000 00 01")
    )
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.new_clients == 0
    assert summary.converted_new_clients == 0


def test_summary_counts_a_work_order_created_after_the_period_ends(db_session: Session) -> None:
    """A conversation on the last day of the period followed by a work order
    in the next one still is that period's conversion (product ask,
    2026-10-24) - nothing is cut at the period's end."""
    _call(db_session, external_id="a", day=10, client="9990000001", talk_sec=40, topic_tag=TOPIC)
    db_session.add(_wo("LATE", datetime(2026, 10, 12, 9, 0, tzinfo=UTC), phone="+7 999 000 00 01"))
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.new_clients == 1
    assert summary.converted_new_clients == 1
    assert summary.work_orders_new_clients == 1


def _example_scenario(db_session: Session) -> None:
    """Product example (shifted into October): the number talks on day 2 and
    day 5, a work order appears on day 12, it talks again on day 14, and a
    second work order appears on day 16."""
    _call(db_session, external_id="c1", day=2, client="9990000001", talk_sec=40, topic_tag=TOPIC)
    _call(db_session, external_id="c2", day=5, client="9990000001", talk_sec=40, topic_tag=TOPIC)
    _call(db_session, external_id="c3", day=14, client="9990000001", talk_sec=40, topic_tag=TOPIC)
    db_session.add(_wo("WO-12", datetime(2026, 10, 12, 9, 0, tzinfo=UTC), phone="+7 999 000 00 01"))
    db_session.add(_wo("WO-16", datetime(2026, 10, 16, 9, 0, tzinfo=UTC), phone="+7 999 000 00 01"))
    db_session.commit()


def test_summary_work_order_belongs_to_the_period_of_the_call_before_it(
    db_session: Session,
) -> None:
    _example_scenario(db_session)

    # "September" (days 1-10): one unique converted number, via WO-12 only -
    # WO-16 comes after the next conversation (day 14) and belongs to it.
    first = conversion_service.get_conversion_summary(
        db_session, date(2026, 10, 1), date(2026, 10, 10)
    )
    assert first.new_clients == 1
    assert first.converted_new_clients == 1
    assert first.work_orders_new_clients == 1

    # "October" (days 11-20): the number already had WO-12 before its first
    # call of the period, so it is an existing client, not a new one.
    second = conversion_service.get_conversion_summary(
        db_session, date(2026, 10, 11), date(2026, 10, 20)
    )
    assert second.new_clients == 0
    assert second.conversion_pct is None


def test_conversation_tab_matches_the_same_example(db_session: Session) -> None:
    _example_scenario(db_session)

    first = conversion_service.list_conversion(db_session, date(2026, 10, 1), date(2026, 10, 10))
    second = conversion_service.list_conversion(db_session, date(2026, 10, 11), date(2026, 10, 20))

    assert [(g.work_order_number, len(g.calls)) for g in first] == [("WO-12", 2)]
    assert [(g.work_order_number, len(g.calls)) for g in second] == [("WO-16", 1)]
    assert second[0].is_existing is True


def test_a_later_missed_call_does_not_cut_the_work_order_window(db_session: Session) -> None:
    """Only a real conversation ends the search window - a missed call after
    the period does not."""
    _call(db_session, external_id="a", day=10, client="9990000001", talk_sec=40, topic_tag=TOPIC)
    _call(db_session, external_id="missed", day=11, client="9990000001")
    db_session.add(_wo("WO", datetime(2026, 10, 12, 9, 0, tzinfo=UTC), phone="+7 999 000 00 01"))
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.converted_new_clients == 1


# ---- Конверсия существующих клиентов ----------------------------------------


def test_existing_clients_with_only_finished_orders_are_counted(db_session: Session) -> None:
    # A: earlier order closed, talks, gets a new order after -> converted.
    _call(db_session, external_id="a", client="9990000001", talk_sec=40, topic_tag=TOPIC)
    db_session.add(
        _wo(
            "A-OLD",
            datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 01",
            status="Закрыт",
        )
    )
    db_session.add(
        _wo("A-NEW", datetime(2026, 10, 10, 12, 0, tzinfo=UTC), phone="+7 999 000 00 01")
    )
    # B: earlier order was refused ("Отказ" counts as finished), no new order.
    _call(db_session, external_id="b", client="9990000002", talk_sec=40, topic_tag=TOPIC)
    db_session.add(
        _wo(
            "B-OLD",
            datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 02",
            status="Отказ",
        )
    )
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.new_clients == 0
    assert summary.existing_topic_phones == 2
    assert summary.existing_excluded == 0
    assert summary.existing_clients == 2
    assert summary.converted_existing_clients == 1
    assert summary.work_orders_existing_clients == 1
    assert summary.existing_conversion_pct == 50.0


def test_existing_client_with_an_order_in_progress_is_excluded(db_session: Session) -> None:
    """They are most likely calling about the repair in progress, not to
    book a new one - their calls stay out of the conversion entirely."""
    _call(db_session, external_id="a", client="9990000001", talk_sec=40, topic_tag=TOPIC)
    db_session.add(
        _wo(
            "DONE",
            datetime(2026, 2, 1, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 01",
            status="Закрыт",
        )
    )
    db_session.add(
        _wo(
            "OPEN",
            datetime(2026, 9, 28, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 01",
            status="В работе",
        )
    )
    db_session.add(
        _wo("AFTER", datetime(2026, 10, 10, 12, 0, tzinfo=UTC), phone="+7 999 000 00 01")
    )
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.existing_topic_phones == 1
    assert summary.existing_excluded == 1
    assert summary.existing_clients == 0
    assert summary.converted_existing_clients == 0
    assert summary.existing_conversion_pct is None
    # ... and it is not a new client either.
    assert summary.new_clients == 0


def test_a_work_order_created_after_the_call_does_not_make_a_client_open(
    db_session: Session,
) -> None:
    """Only orders that existed BEFORE the first call decide whether the
    client is counted - the order the call led to (still open) must not
    exclude the very client it converted."""
    _call(db_session, external_id="a", client="9990000001", talk_sec=40, topic_tag=TOPIC)
    db_session.add(
        _wo(
            "OLD", datetime(2026, 3, 1, 9, 0, tzinfo=UTC), phone="+7 999 000 00 01", status="Закрыт"
        )
    )
    db_session.add(
        _wo(
            "NEW-OPEN",
            datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
            phone="+7 999 000 00 01",
            status="В работе",
        )
    )
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.existing_clients == 1
    assert summary.converted_existing_clients == 1


# ---- "Существующий" клиент: статус заказ-наряда на день звонка ---------------


def _closed_at(db_session: Session, wo: WorkOrder, when: datetime, status: str = "Закрыт") -> None:
    """Record, in 1C's status history, the moment `wo` moved to `status`."""
    from app.models.work_order_status_history import WorkOrderStatusHistory

    db_session.flush()
    db_session.add(
        WorkOrderStatusHistory(
            work_order_id=wo.id, version_number=2, changed_at=when, status=status, author="t"
        )
    )


def test_order_closed_on_an_earlier_day_does_not_exclude_the_client(db_session: Session) -> None:
    _call(db_session, external_id="a", client="9990000001", talk_sec=40, topic_tag=TOPIC)
    wo = _wo(
        "OLD", datetime(2026, 10, 1, 9, 0, tzinfo=UTC), phone="+7 999 000 00 01", status="Закрыт"
    )
    db_session.add(wo)
    _closed_at(db_session, wo, datetime(2026, 10, 9, 20, 0, tzinfo=UTC))  # day before the call
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.existing_clients == 1
    assert summary.existing_excluded == 0


def test_order_closed_on_the_day_of_the_call_still_excludes_the_client(db_session: Session) -> None:
    """Workshop orders go from "Заявка" to "Закрыт" within a single day, so
    a call on the closing day is most likely about that very repair."""
    _call(db_session, external_id="a", client="9990000001", talk_sec=40, topic_tag=TOPIC)
    wo = _wo(
        "SAME-DAY",
        datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
        phone="+7 999 000 00 01",
        status="Закрыт",
    )
    db_session.add(wo)
    # Closed at 07:00 MSK on the 10th - earlier than the 12:00 call, same day.
    _closed_at(db_session, wo, datetime(2026, 10, 10, 4, 0, tzinfo=UTC))
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.existing_excluded == 1
    assert summary.existing_clients == 0


def test_order_closed_after_the_call_day_excludes_the_client(db_session: Session) -> None:
    _call(db_session, external_id="a", client="9990000001", talk_sec=40, topic_tag=TOPIC)
    wo = _wo(
        "LATER", datetime(2026, 10, 1, 9, 0, tzinfo=UTC), phone="+7 999 000 00 01", status="Закрыт"
    )
    db_session.add(wo)
    _closed_at(db_session, wo, datetime(2026, 10, 12, 9, 0, tzinfo=UTC))  # still open on the 10th
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.existing_excluded == 1


def test_finish_day_falls_back_to_closed_date_then_document_date(db_session: Session) -> None:
    # No history: closed_date decides (closed on the call day -> excluded)...
    _call(db_session, external_id="a", client="9990000001", talk_sec=40, topic_tag=TOPIC)
    db_session.add(
        _wo(
            "CLOSED-TODAY",
            datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 01",
            status="Закрыт",
            closed_date=datetime(2026, 10, 10, 15, 0, tzinfo=UTC),
        )
    )
    # ... and a refusal, which never has closed_date, falls back to its
    # document date (long before the call -> fine).
    _call(db_session, external_id="b", client="9990000002", talk_sec=40, topic_tag=TOPIC)
    db_session.add(
        _wo(
            "REFUSED",
            datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 02",
            status="Отказ",
        )
    )
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.existing_topic_phones == 2
    assert summary.existing_excluded == 1
    assert summary.existing_clients == 1


# ---- Цифры рядом с бубликами: звонки новых / существующих клиентов -----------


def test_summary_figures_beside_the_donuts_are_unique_numbers(db_session: Session) -> None:
    # NEW number with many calls: 3 missed, our callback with a topic
    # conversation, a second conversation -> ONE number, and a target one.
    for i, hour in enumerate((9, 10, 11)):
        _call(db_session, external_id=f"n{i}", hour_msk=hour, client="9990000001")
    _call(
        db_session,
        external_id="n-cb",
        hour_msk=12,
        call_type="OUT",
        client="9990000001",
        talk_sec=30,
        topic_tag=TOPIC,
    )
    _call(
        db_session,
        external_id="n-in",
        hour_msk=13,
        client="9990000001",
        talk_sec=30,
        topic_tag=TOPIC,
    )
    # A new number that only had one missed call: a new client, not a target.
    _call(db_session, external_id="only-missed", client="9990000002")
    # EXISTING (earlier order long closed), a conversation with a topic: target.
    _call(db_session, external_id="e0", hour_msk=9, client="9990000003")
    _call(
        db_session, external_id="e1", hour_msk=10, client="9990000003", talk_sec=40, topic_tag=TOPIC
    )
    db_session.add(
        _wo(
            "E-OLD",
            datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 03",
            status="Закрыт",
        )
    )
    # EXISTING but an order is in progress -> not counted anywhere.
    _call(db_session, external_id="x", client="9990000004", talk_sec=40, topic_tag=TOPIC)
    db_session.add(
        _wo(
            "X-OPEN",
            datetime(2026, 9, 20, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 04",
            status="В работе",
        )
    )
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.calls_total == 5 + 1 + 2 + 1
    # Target = new + existing numbers WITH a topic conversation (the
    # only-missed number and the in-progress existing one are not).
    assert summary.new_clients == 1
    assert summary.existing_clients == 1
    assert summary.target_phones == summary.new_clients + summary.existing_clients == 2
    assert summary.existing_excluded == 1


def test_unanswered_numbers_are_missed_and_never_reached_in_the_period(
    db_session: Session,
) -> None:
    # NEW: missed, never called back -> unanswered.
    _call(db_session, external_id="a", client="9990000001")
    # NEW: missed, then our callback reached them -> answered.
    _call(db_session, external_id="b0", hour_msk=9, client="9990000002")
    _call(
        db_session, external_id="b1", hour_msk=10, call_type="OUT", client="9990000002", talk_sec=30
    )
    # NEW: our callback did not reach them (no talk) -> still unanswered.
    _call(db_session, external_id="c0", hour_msk=9, client="9990000003")
    _call(db_session, external_id="c1", hour_msk=10, call_type="OUT", client="9990000003")
    # NEW: reached first, missed again later with no callback -> unanswered.
    _call(db_session, external_id="d0", hour_msk=9, client="9990000004", talk_sec=30)
    _call(db_session, external_id="d1", hour_msk=15, client="9990000004")
    # NEW: a talk of under 5 seconds is not a conversation -> unanswered.
    _call(db_session, external_id="e0", hour_msk=9, client="9990000005")
    _call(
        db_session, external_id="e1", hour_msk=10, call_type="OUT", client="9990000005", talk_sec=3
    )
    # EXISTING (closed earlier): missed and never reached.
    _call(db_session, external_id="f", client="9990000006")
    db_session.add(
        _wo(
            "F-OLD",
            datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 06",
            status="Закрыт",
        )
    )
    # No missed call at all -> not unanswered.
    _call(db_session, external_id="g", client="9990000007", talk_sec=40)
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)
    groups = {g.client: g for g in conversion_service.list_conversion(db_session, DAY, DAY)}

    assert summary.unanswered_new == 4  # 1, 3, 4, 5
    assert summary.unanswered_existing == 1  # 6
    assert groups["9990000001"].phone_unanswered is True
    assert groups["9990000002"].phone_unanswered is False
    assert groups["9990000007"].phone_unanswered is False


def test_groups_carry_the_client_class_of_every_phone(db_session: Session) -> None:
    _call(db_session, external_id="a", client="9990000001")  # new, no conversation
    _call(db_session, external_id="b", client="9990000002", talk_sec=40, topic_tag=TOPIC)
    db_session.add(
        _wo(
            "B-OLD",
            datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 02",
            status="Закрыт",
        )
    )
    db_session.commit()

    groups = {g.client: g for g in conversion_service.list_conversion(db_session, DAY, DAY)}

    assert (groups["9990000001"].client_class, groups["9990000001"].segment) == ("new", "none")
    assert (groups["9990000002"].client_class, groups["9990000002"].segment) == (
        "existing_counted",
        "existing_counted",
    )


# ---- Правила статуса на момент звонка, гарантия, цех -------------------------


def _history(db_session: Session, wo: WorkOrder, *entries: tuple[datetime, str]) -> None:
    """Real 1C status history entries for `wo`, oldest first."""
    from app.models.work_order_status_history import WorkOrderStatusHistory

    db_session.flush()
    for version, (changed_at, status) in enumerate(entries, start=1):
        db_session.add(
            WorkOrderStatusHistory(
                work_order_id=wo.id,
                version_number=version,
                changed_at=changed_at,
                status=status,
                author="t",
            )
        )


def test_each_call_is_judged_by_the_order_status_at_that_minute(db_session: Session) -> None:
    """09:00 call while the order is in progress -> excluded; 15:00 call,
    after it was closed the day before... (here: closed on an earlier day) ->
    counted. The number counts once, through the call that was not excluded."""
    # Two topic conversations on the 10th (MSK): 09:00 and 15:00.
    _call(
        db_session,
        external_id="early",
        hour_msk=9,
        client="9990000001",
        talk_sec=40,
        topic_tag=TOPIC,
    )
    _call(
        db_session,
        external_id="late",
        hour_msk=15,
        client="9990000001",
        talk_sec=40,
        topic_tag=TOPIC,
    )
    wo = _wo(
        "OLD", datetime(2026, 10, 1, 9, 0, tzinfo=UTC), phone="+7 999 000 00 01", status="Закрыт"
    )
    db_session.add(wo)
    # In progress until 12:00 MSK on the 10th, closed then (same day as both
    # calls): at 09:00 it was open, at 15:00 it was closed THAT day.
    _history(
        db_session,
        wo,
        (datetime(2026, 10, 1, 9, 0, tzinfo=UTC), "В работе"),
        (datetime(2026, 10, 10, 9, 0, tzinfo=UTC), "Закрыт"),
    )
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    # 09:00 -> open order; 15:00 -> closed the same date -> both excluded.
    assert summary.target_phones == 0
    assert summary.existing_excluded == 1


def test_a_later_call_after_the_closing_day_is_counted(db_session: Session) -> None:
    _call(
        db_session,
        external_id="early",
        day=10,
        hour_msk=9,
        client="9990000001",
        talk_sec=40,
        topic_tag=TOPIC,
    )
    _call(
        db_session,
        external_id="later",
        day=12,
        hour_msk=9,
        client="9990000001",
        talk_sec=40,
        topic_tag=TOPIC,
    )
    wo = _wo(
        "OLD", datetime(2026, 10, 1, 9, 0, tzinfo=UTC), phone="+7 999 000 00 01", status="Закрыт"
    )
    db_session.add(wo)
    _history(
        db_session,
        wo,
        (datetime(2026, 10, 1, 9, 0, tzinfo=UTC), "В работе"),
        (datetime(2026, 10, 10, 9, 0, tzinfo=UTC), "Закрыт"),
    )
    db_session.commit()

    summary = conversion_service.get_conversion_summary(
        db_session, date(2026, 10, 10), date(2026, 10, 12)
    )

    # The 10th call is excluded (closed that very day), the 12th is fine.
    assert summary.existing_clients == 1
    assert summary.existing_excluded == 0


def test_a_refusal_on_the_day_of_the_call_does_not_exclude(db_session: Session) -> None:
    """Only "Закрыт" reached on the call's own date means a car being handed
    over right now; a refusal that day does not."""
    _call(
        db_session, external_id="a", hour_msk=15, client="9990000001", talk_sec=40, topic_tag=TOPIC
    )
    wo = _wo(
        "REFUSED", datetime(2026, 10, 1, 9, 0, tzinfo=UTC), phone="+7 999 000 00 01", status="Отказ"
    )
    db_session.add(wo)
    _history(
        db_session,
        wo,
        (datetime(2026, 10, 1, 9, 0, tzinfo=UTC), "Заявка"),
        (datetime(2026, 10, 10, 6, 0, tzinfo=UTC), "Отказ"),
    )
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.existing_clients == 1


def test_an_order_closed_later_the_same_day_was_open_at_call_time(db_session: Session) -> None:
    _call(
        db_session, external_id="a", hour_msk=10, client="9990000001", talk_sec=40, topic_tag=TOPIC
    )
    wo = _wo(
        "OPEN-THEN-CLOSED",
        datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
        phone="+7 999 000 00 01",
        status="Закрыт",
    )
    db_session.add(wo)
    _history(
        db_session,
        wo,
        (datetime(2026, 10, 1, 9, 0, tzinfo=UTC), "В работе"),
        (datetime(2026, 10, 10, 15, 0, tzinfo=UTC), "Закрыт"),  # 18:00 MSK, after the 10:00 call
    )
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.existing_excluded == 1
    assert summary.existing_clients == 0


def test_warranty_orders_are_ignored_everywhere(db_session: Session) -> None:
    from app.models.app_settings import AppSettings

    db_session.add(AppSettings(id=1, warranty_repair_types=["Гарантийный"]))
    # A: only an open warranty order -> still a NEW client (it is skipped),
    # and a warranty order created after the call is not a conversion.
    _call(db_session, external_id="a", client="9990000001", talk_sec=40, topic_tag=TOPIC)
    db_session.add(
        _wo(
            "A-WARR",
            datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 01",
            status="В работе",
            repair_type="Гарантийный",
        )
    )
    db_session.add(
        _wo(
            "A-WARR-AFTER",
            datetime(2026, 10, 10, 15, 0, tzinfo=UTC),
            phone="+7 999 000 00 01",
            repair_type="Гарантийный",
        )
    )
    # B: a closed ordinary order + an OPEN warranty one -> the open warranty
    # order must not exclude the client.
    _call(db_session, external_id="b", client="9990000002", talk_sec=40, topic_tag=TOPIC)
    db_session.add(
        _wo(
            "B-OLD",
            datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 02",
            status="Закрыт",
        )
    )
    db_session.add(
        _wo(
            "B-WARR",
            datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
            phone="+7 999 000 00 02",
            status="В работе",
            repair_type="Гарантийный",
        )
    )
    # A real, ordinary order for B after the call -> a conversion.
    db_session.add(
        _wo(
            "B-NEW",
            datetime(2026, 10, 10, 15, 0, tzinfo=UTC),
            phone="+7 999 000 00 02",
            repair_type="Платный",
        )
    )
    db_session.commit()

    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert summary.new_clients == 1  # A
    assert summary.converted_new_clients == 0  # its only later order is warranty
    assert summary.existing_clients == 1  # B
    assert summary.existing_excluded == 0
    assert summary.converted_existing_clients == 1
    # Created in the period: B-NEW counts, the warranty A-WARR-AFTER does not.
    assert summary.work_orders_total == 1


def test_department_filter_limits_calls_and_conversions_to_that_workshop(
    db_session: Session,
) -> None:
    from app.models.department import Department
    from app.models.workshop import Workshop
    from app.models.workshop_source_department import WorkshopSourceDepartment

    dept = Department(name="Каховка")
    db_session.add(dept)
    db_session.flush()
    body = Workshop(
        department_id=dept.id,
        workshop_type="Кузовной",
        posts_count=1,
        start_time="08:00:00",
        end_time="20:00:00",
        working_days=[0],
    )
    mech = Workshop(
        department_id=dept.id,
        workshop_type="Слесарный",
        posts_count=1,
        start_time="08:00:00",
        end_time="20:00:00",
        working_days=[0],
    )
    db_session.add_all([body, mech])
    db_session.flush()
    db_session.add(WorkshopSourceDepartment(workshop_id=body.id, source_department="Кузовной цех"))
    db_session.add(WorkshopSourceDepartment(workshop_id=mech.id, source_department="Слесарный цех"))

    _call(
        db_session,
        external_id="b",
        client="9990000001",
        talk_sec=40,
        topic_tag=TOPIC,
        workshop_id=body.id,
    )
    _call(
        db_session,
        external_id="m",
        client="9990000002",
        talk_sec=40,
        topic_tag=TOPIC,
        workshop_id=mech.id,
    )
    db_session.add(
        _wo(
            "B-WO",
            datetime(2026, 10, 10, 15, 0, tzinfo=UTC),
            phone="+7 999 000 00 01",
            department="Кузовной цех",
        )
    )
    db_session.add(
        _wo(
            "M-WO",
            datetime(2026, 10, 10, 15, 0, tzinfo=UTC),
            phone="+7 999 000 00 02",
            department="Слесарный цех",
        )
    )
    db_session.commit()

    everything = conversion_service.get_conversion_summary(db_session, DAY, DAY)
    body_only = conversion_service.get_conversion_summary(db_session, DAY, DAY, ["Кузовной цех"])
    unmapped = conversion_service.get_conversion_summary(db_session, DAY, DAY, ["Нет такого цеха"])

    assert (everything.calls_total, everything.target_phones, everything.work_orders_total) == (
        2,
        2,
        2,
    )
    assert (body_only.calls_total, body_only.target_phones, body_only.work_orders_new_clients) == (
        1,
        1,
        1,
    )
    assert body_only.work_orders_total == 1
    assert (unmapped.calls_total, unmapped.target_phones, unmapped.work_orders_total) == (0, 0, 0)
    groups = conversion_service.list_conversion(db_session, DAY, DAY, ["Слесарный цех"])
    assert [g.client for g in groups] == ["9990000002"]


# ---- "Дошли до заказ-наряда" / список заказ-нарядов бублика -------------------


def test_converted_phone_has_one_conversion_row_and_its_work_orders_are_listed(
    db_session: Session,
) -> None:
    # One NEW number: conversation, a work order, a later call (now an
    # existing client's call, no work order) and a second work order after
    # that - two groups with work orders, ONE conversion row.
    _call(
        db_session, external_id="a1", hour_msk=9, client="9990000001", talk_sec=40, topic_tag=TOPIC
    )
    _call(
        db_session, external_id="a2", hour_msk=17, client="9990000001", talk_sec=40, topic_tag=TOPIC
    )
    first = _wo(
        "WO-1", datetime(2026, 10, 10, 8, 0, tzinfo=UTC), phone="+7 999 000 00 01", status="Закрыт"
    )  # 11:00 MSK
    second = _wo(
        "WO-2", datetime(2026, 10, 10, 16, 0, tzinfo=UTC), phone="+7 999 000 00 01"
    )  # 19:00 MSK
    db_session.add_all([first, second])
    # A number that did not convert.
    _call(db_session, external_id="b", client="9990000002", talk_sec=40, topic_tag=TOPIC)
    db_session.commit()

    groups = {
        g.work_order_number: g for g in conversion_service.list_conversion(db_session, DAY, DAY)
    }
    assert groups["WO-1"].conversion_row is True  # the converted number's first counted group
    assert groups["WO-2"].conversion_row is False  # same number, later group
    assert groups[None].conversion_row is False  # the number that did not convert
    assert sum(g.conversion_row for g in groups.values()) == 1

    ids = conversion_service.conversion_work_order_ids(db_session, DAY, DAY, "new")
    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)
    # Exactly the work orders counted in "Заказ-нарядов".
    assert len(ids) == summary.work_orders_new_clients
    assert len(ids) == 2
    assert conversion_service.conversion_work_order_ids(db_session, DAY, DAY, "existing") == []


# ---- Часовой пояс дат заказ-нарядов -----------------------------------------


def test_work_order_dates_are_compared_as_real_moments(db_session: Session) -> None:
    """The importer stores a work order's 1C Moscow clock reading as if it
    were UTC (3 h late). A work order created at 11:00 MSK, an hour BEFORE a
    12:00 MSK call, is stored as 11:00Z - which, read naively as an instant,
    would look 2 hours AFTER the call and be miscounted as its conversion."""
    _call(
        db_session, external_id="a", hour_msk=12, client="9990000001", talk_sec=40, topic_tag=TOPIC
    )
    db_session.add(
        _wo(
            "BEFORE",
            datetime(2026, 10, 10, 8, 0, tzinfo=UTC),
            phone="+7 999 000 00 01",
            status="Закрыт",
        )  # 11:00 MSK
    )
    # ... and one created at 13:00 MSK, an hour AFTER the call.
    db_session.add(
        _wo("AFTER", datetime(2026, 10, 10, 10, 0, tzinfo=UTC), phone="+7 999 000 00 01")
    )
    db_session.commit()

    (group,) = conversion_service.list_conversion(db_session, DAY, DAY)
    summary = conversion_service.get_conversion_summary(db_session, DAY, DAY)

    assert group.work_order_number == "AFTER"
    assert group.is_existing is True  # BEFORE already existed at 12:00
    assert summary.work_orders_total == 2  # both created on the 10th
