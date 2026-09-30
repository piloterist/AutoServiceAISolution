"""Tests for services/telephony_stats_service.py - the missed-call outcome
analysis ported from Zeon_AI/stats.py (see that module's docstring) and the
per-source rollup used by Settings -> IP-телефония's "Итог по каждому
источнику" table.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from app.models.call_record import CallRecord
from app.models.employee import Employee
from app.models.phone_source import PhoneSource
from app.services import telephony_stats_service as stats

DAY = date(2026, 9, 20)


def _call(
    db_session: Session,
    *,
    external_id: str,
    hour_msk: int,
    minute_msk: int = 0,
    call_type: str,
    client: str | None,
    line: str | None,
    talk_sec: int = 0,
    wait_sec: int = 10,
    rang_not_answered: list[str] | None = None,
) -> CallRecord:
    # MSK is UTC+3 - see stats.py's own _MSK constant/docstring.
    occurred_at = datetime(2026, 9, 20, hour_msk - 3, minute_msk, tzinfo=UTC)
    call = CallRecord(
        id=uuid.uuid4(),
        provider="zeon",
        external_id=external_id,
        call_date=DAY,
        occurred_at=occurred_at,
        call_type=call_type,
        client=client,
        line=line,
        operator="302",
        rang_not_answered=rang_not_answered,
        wait_sec=wait_sec,
        talk_sec=talk_sec,
        answered=talk_sec > 0,
    )
    db_session.add(call)
    return call


@pytest.fixture()
def scenario(db_session: Session) -> None:
    """One day, two lines, three missed-caller outcomes:
    - client A (line "pan"): missed, then reached by our callback ->
      called_back_reached.
    - client B (line "pan"): missed, no reaction at all -> no_reaction.
    - client C (line "direct"): missed, then calls back themselves and is
      answered -> client_called_back.
    Plus one answered inbound on each line so answered/pickup numbers are
    also exercised, not just the missed path.
    """
    _call(
        db_session,
        external_id="1",
        hour_msk=10,
        call_type="IN",
        client="9990000001",
        line="pan",
        talk_sec=60,
    )
    _call(
        db_session,
        external_id="2",
        hour_msk=11,
        call_type="IN",
        client="9990000002",
        line="pan",
        wait_sec=10,
    )
    _call(
        db_session,
        external_id="3",
        hour_msk=11,
        minute_msk=30,
        call_type="OUT",
        client="9990000002",
        line=None,
        talk_sec=30,
    )
    _call(
        db_session,
        external_id="4",
        hour_msk=12,
        call_type="IN",
        client="9990000003",
        line="pan",
        wait_sec=8,
    )
    _call(
        db_session,
        external_id="5",
        hour_msk=13,
        call_type="IN",
        client="9990000004",
        line="direct",
        wait_sec=6,
    )
    _call(
        db_session,
        external_id="6",
        hour_msk=13,
        minute_msk=30,
        call_type="IN",
        client="9990000004",
        line="direct",
        talk_sec=20,
    )
    db_session.commit()


def test_compute_day_stats_summary(db_session: Session, scenario: None) -> None:
    doc = stats.compute_day_stats(db_session, DAY)
    summary = doc["summary"]

    assert summary["inbound"]["total"] == 5
    assert summary["inbound"]["answered"] == 2
    assert summary["inbound"]["missed"] == 3
    assert summary["inbound"]["missed_pct"] == 60.0
    assert summary["inbound"]["unique_missed_callers"] == 3

    outcomes = summary["missed_clients_outcome"]
    assert outcomes["called_back_reached"] == 1
    assert outcomes["called_back_not_reached"] == 0
    assert outcomes["client_called_back"] == 1
    assert outcomes["no_reaction"] == 1

    assert summary["outbound"]["total"] == 1
    assert summary["outbound"]["callbacks_to_missed"] == 1


def test_compute_day_stats_missed_client_outcomes(db_session: Session, scenario: None) -> None:
    doc = stats.compute_day_stats(db_session, DAY)
    by_client = {m["client"]: m for m in doc["missed_clients"]}

    assert by_client["9990000002"]["outcome"] == "called_back_reached"
    assert by_client["9990000003"]["outcome"] == "no_reaction"
    assert by_client["9990000004"]["outcome"] == "client_called_back"


def test_compute_day_stats_by_line(db_session: Session, scenario: None) -> None:
    doc = stats.compute_day_stats(db_session, DAY)
    by_line = {row["line"]: row for row in doc["by_line"]}

    assert by_line["pan"]["inbound"] == 3
    assert by_line["pan"]["answered"] == 1
    assert by_line["pan"]["missed"] == 2

    assert by_line["direct"]["inbound"] == 2
    assert by_line["direct"]["answered"] == 1
    assert by_line["direct"]["missed"] == 1


def test_compute_source_summary_groups_by_phone_source(db_session: Session, scenario: None) -> None:
    pan_source = PhoneSource(
        line_code="pan", name="2GIS", group_name="Карты и каталоги", sort_order=1
    )
    db_session.add(pan_source)
    db_session.commit()

    rows = stats.compute_source_summary(db_session, DAY, DAY, [pan_source])
    by_line = {row.line_code: row for row in rows}

    pan = by_line["pan"]
    assert pan.name == "2GIS"
    assert pan.inbound_total == 3
    assert pan.missed == 2
    assert pan.unique_missed_callers == 2
    assert pan.outcome_called_back_reached == 1
    assert pan.outcome_no_reaction == 1

    # "direct" has no matching PhoneSource row - falls back to a synthetic
    # "unknown line" entry rather than being dropped, per phone_source.py's
    # module docstring.
    direct = by_line["direct"]
    assert direct.name == "Неизвестная линия direct"
    assert direct.outcome_client_called_back == 1


def test_list_line_calls_includes_incoming_and_our_callback(
    db_session: Session, scenario: None
) -> None:
    events = stats.list_line_calls(db_session, DAY, DAY, "pan")
    roles = [(e.time[-8:], e.direction, e.role, e.client) for e in events]

    assert roles == [
        ("10:00:00", "in", "incoming", "9990000001"),
        ("11:00:00", "in", "incoming", "9990000002"),
        ("11:30:00", "out", "callback", "9990000002"),
        ("12:00:00", "in", "incoming", "9990000003"),
    ]


def test_list_line_calls_labels_client_self_recall(db_session: Session, scenario: None) -> None:
    events = stats.list_line_calls(db_session, DAY, DAY, "direct")
    roles = [(e.time[-8:], e.direction, e.role, e.client) for e in events]

    assert roles == [
        ("13:00:00", "in", "incoming", "9990000004"),
        ("13:30:00", "in", "client_recall", "9990000004"),
    ]


def test_compute_day_stats_ignores_employee_phone(db_session: Session, scenario: None) -> None:
    """A known employee's phone never counts toward any telephony reporting
    (per product spec, 2026-09-30 - replaces the old standalone "Исключения"
    table). scenario's own client "9990000003" is a real no_reaction miss on
    line "pan" - matching it to an employee should drop it from every count."""
    db_session.add(Employee(full_name="Служебный номер", specialty="Механик", phone="9990000003"))
    db_session.commit()

    doc = stats.compute_day_stats(db_session, DAY)
    summary = doc["summary"]

    assert summary["inbound"]["total"] == 4  # was 5
    assert summary["inbound"]["missed"] == 2  # was 3
    assert summary["missed_clients_outcome"]["no_reaction"] == 0  # was 1
    assert "9990000003" not in {m["client"] for m in doc["missed_clients"]}


def test_compute_source_summary_ignores_employee_phone(db_session: Session, scenario: None) -> None:
    db_session.add(Employee(full_name="Служебный номер", specialty="Механик", phone="9990000003"))
    db_session.commit()
    pan_source = PhoneSource(
        line_code="pan", name="2GIS", group_name="Карты и каталоги", sort_order=1
    )
    db_session.add(pan_source)
    db_session.commit()

    rows = stats.compute_source_summary(db_session, DAY, DAY, [pan_source])
    pan = next(r for r in rows if r.line_code == "pan")

    assert pan.inbound_total == 2  # was 3
    assert pan.unique_missed_callers == 1  # was 2


def test_list_line_calls_ignores_employee_phone(db_session: Session, scenario: None) -> None:
    db_session.add(Employee(full_name="Служебный номер", specialty="Механик", phone="9990000003"))
    db_session.commit()

    events = stats.list_line_calls(db_session, DAY, DAY, "pan")
    clients = {e.client for e in events}

    assert "9990000003" not in clients


def test_list_line_calls_surfaces_rang_not_answered(db_session: Session) -> None:
    _call(
        db_session,
        external_id="1",
        hour_msk=10,
        call_type="IN",
        client="9990000099",
        line="pan",
        rang_not_answered=["302", "300", "308"],
    )
    db_session.commit()

    events = stats.list_line_calls(db_session, DAY, DAY, "pan")

    assert len(events) == 1
    assert events[0].rang_not_answered == ["302", "300", "308"]


def test_compute_source_summary_defaults_to_no_reaction_when_never_followed_up(
    db_session: Session, scenario: None
) -> None:
    rows = stats.compute_source_summary(db_session, DAY, DAY, [])
    pan = next(r for r in rows if r.line_code == "pan")
    assert pan.reached_pct == pytest.approx(50.0)  # 1 of 2 unique missed callers reached
