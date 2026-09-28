"""Tests for telephony_stats_service.get_open_missed_calls - the Planner
phone-icon badge's resolution rules (see that function's docstring): a
rolling 2-Moscow-calendar-day window, >=5s of real talk time to count as
"reached", and one real contact clears every earlier open miss from that
same number, not just the one immediately before it.
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.call_record import CallRecord
from app.models.phone_source import PhoneSource
from app.services import telephony_stats_service as stats

_MSK = timezone(timedelta(hours=3))

# "Now" fixed at 2026-09-20 18:00 MSK for every test below - today=Sep 20,
# yesterday=Sep 19, the day before that (Sep 18) has already aged out.
NOW = datetime(2026, 9, 20, 15, 0, 0, tzinfo=UTC)


def _call(
    db_session: Session,
    *,
    external_id: str,
    when_msk: datetime,
    call_type: str,
    client: str | None,
    line: str | None = None,
    talk_sec: int = 0,
    rang_not_answered: list[str] | None = None,
) -> CallRecord:
    occurred_at = when_msk.replace(tzinfo=_MSK).astimezone(UTC)
    call = CallRecord(
        id=uuid.uuid4(),
        provider="zeon",
        external_id=external_id,
        call_date=when_msk.date(),
        occurred_at=occurred_at,
        call_type=call_type,
        client=client,
        line=line,
        operator="302",
        rang_not_answered=rang_not_answered,
        wait_sec=10,
        talk_sec=talk_sec,
        answered=talk_sec > 0,
    )
    db_session.add(call)
    return call


def test_single_unresolved_inbound_miss_shows_up(db_session: Session) -> None:
    _call(
        db_session,
        external_id="1",
        when_msk=datetime(2026, 9, 20, 10, 0),
        call_type="IN",
        client="9990000001",
        line="pan",
    )
    db_session.commit()

    calls = stats.get_open_missed_calls(db_session, now=NOW)

    assert len(calls) == 1
    assert calls[0].client == "9990000001"
    assert calls[0].direction == "in"
    assert calls[0].source_label == "Неизвестная линия pan"


def test_multiple_misses_from_same_number_all_count(db_session: Session) -> None:
    for i in range(3):
        _call(
            db_session,
            external_id=f"miss-{i}",
            when_msk=datetime(2026, 9, 20, 10, i),
            call_type="IN",
            client="9990000002",
            line="pan",
        )
    db_session.commit()

    calls = stats.get_open_missed_calls(db_session, now=NOW)

    assert len(calls) == 3
    assert all(c.client == "9990000002" for c in calls)


def test_real_callback_clears_every_earlier_miss_from_that_number(db_session: Session) -> None:
    for i in range(3):
        _call(
            db_session,
            external_id=f"miss-{i}",
            when_msk=datetime(2026, 9, 20, 10, i),
            call_type="IN",
            client="9990000003",
            line="pan",
        )
    _call(
        db_session,
        external_id="callback",
        when_msk=datetime(2026, 9, 20, 11, 0),
        call_type="OUT",
        client="9990000003",
        talk_sec=30,
    )
    db_session.commit()

    assert stats.get_open_missed_calls(db_session, now=NOW) == []


def test_client_recall_answered_also_resolves(db_session: Session) -> None:
    _call(
        db_session,
        external_id="miss",
        when_msk=datetime(2026, 9, 20, 10, 0),
        call_type="IN",
        client="9990000004",
        line="pan",
    )
    _call(
        db_session,
        external_id="recall",
        when_msk=datetime(2026, 9, 20, 10, 30),
        call_type="IN",
        client="9990000004",
        line="pan",
        talk_sec=45,
    )
    db_session.commit()

    assert stats.get_open_missed_calls(db_session, now=NOW) == []


def test_short_answered_call_under_5s_does_not_resolve_and_is_not_counted(
    db_session: Session,
) -> None:
    _call(
        db_session,
        external_id="miss",
        when_msk=datetime(2026, 9, 20, 10, 0),
        call_type="IN",
        client="9990000005",
        line="pan",
    )
    _call(
        db_session,
        external_id="brief",
        when_msk=datetime(2026, 9, 20, 10, 30),
        call_type="OUT",
        client="9990000005",
        talk_sec=3,
    )
    db_session.commit()

    calls = stats.get_open_missed_calls(db_session, now=NOW)

    assert len(calls) == 1
    assert calls[0].id == "miss"


def test_exactly_5s_counts_as_reached(db_session: Session) -> None:
    _call(
        db_session,
        external_id="miss",
        when_msk=datetime(2026, 9, 20, 10, 0),
        call_type="IN",
        client="9990000006",
        line="pan",
    )
    _call(
        db_session,
        external_id="callback",
        when_msk=datetime(2026, 9, 20, 10, 30),
        call_type="OUT",
        client="9990000006",
        talk_sec=5,
    )
    db_session.commit()

    assert stats.get_open_missed_calls(db_session, now=NOW) == []


def test_miss_older_than_yesterday_is_excluded(db_session: Session) -> None:
    _call(
        db_session,
        external_id="old-miss",
        when_msk=datetime(2026, 9, 18, 10, 0),
        call_type="IN",
        client="9990000007",
        line="pan",
    )
    db_session.commit()

    assert stats.get_open_missed_calls(db_session, now=NOW) == []


def test_miss_from_yesterday_still_counts(db_session: Session) -> None:
    _call(
        db_session,
        external_id="yesterday-miss",
        when_msk=datetime(2026, 9, 19, 23, 0),
        call_type="IN",
        client="9990000008",
        line="pan",
    )
    db_session.commit()

    calls = stats.get_open_missed_calls(db_session, now=NOW)
    assert len(calls) == 1
    assert calls[0].client == "9990000008"


def test_outbound_missed_callback_shows_up_as_callback_direction(db_session: Session) -> None:
    _call(
        db_session,
        external_id="failed-callback",
        when_msk=datetime(2026, 9, 20, 10, 0),
        call_type="OUT",
        client="9990000009",
    )
    db_session.commit()

    calls = stats.get_open_missed_calls(db_session, now=NOW)
    assert len(calls) == 1
    assert calls[0].direction == "callback"
    assert calls[0].source_label is None  # line only meaningful for IN


def test_fresh_miss_after_resolution_is_not_retroactively_cleared(db_session: Session) -> None:
    _call(
        db_session,
        external_id="miss-1",
        when_msk=datetime(2026, 9, 20, 9, 0),
        call_type="IN",
        client="9990000010",
        line="pan",
    )
    _call(
        db_session,
        external_id="resolved",
        when_msk=datetime(2026, 9, 20, 9, 30),
        call_type="OUT",
        client="9990000010",
        talk_sec=20,
    )
    _call(
        db_session,
        external_id="miss-2",
        when_msk=datetime(2026, 9, 20, 11, 0),
        call_type="IN",
        client="9990000010",
        line="pan",
    )
    db_session.commit()

    calls = stats.get_open_missed_calls(db_session, now=NOW)
    assert len(calls) == 1
    assert calls[0].id == "miss-2"


def test_known_phone_source_label_used(db_session: Session) -> None:
    db_session.add(PhoneSource(line_code="pan", name="2GIS", group_name="Прочие"))
    _call(
        db_session,
        external_id="miss",
        when_msk=datetime(2026, 9, 20, 10, 0),
        call_type="IN",
        client="9990000011",
        line="pan",
    )
    db_session.commit()

    calls = stats.get_open_missed_calls(db_session, now=NOW)
    assert calls[0].source_label == "2GIS"


def test_rang_not_answered_surfaced_for_inbound_miss(db_session: Session) -> None:
    _call(
        db_session,
        external_id="miss",
        when_msk=datetime(2026, 9, 20, 10, 0),
        call_type="IN",
        client="9990000012",
        line="pan",
        rang_not_answered=["302", "300", "308"],
    )
    db_session.commit()

    calls = stats.get_open_missed_calls(db_session, now=NOW)
    assert calls[0].rang_not_answered == ["302", "300", "308"]


def test_rang_not_answered_not_shown_for_outbound_callback(db_session: Session) -> None:
    # Zeon's `lost` isn't a meaningful "who did we try to reach" concept for
    # an outbound attempt - `operator` (who placed it) already covers that -
    # so this stays empty here even if the raw column happened to carry
    # something.
    _call(
        db_session,
        external_id="failed-callback",
        when_msk=datetime(2026, 9, 20, 10, 0),
        call_type="OUT",
        client="9990000013",
        rang_not_answered=["999"],
    )
    db_session.commit()

    calls = stats.get_open_missed_calls(db_session, now=NOW)
    assert calls[0].rang_not_answered == []
