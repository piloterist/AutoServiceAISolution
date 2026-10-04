"""Tests for services/call_workshop_service.py - цех determination for
imported calls (see models/workshop_phone_mapping.py for the settings table
this matches against).
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.models.call_record import (
    CALL_TYPE_IN,
    CALL_TYPE_OUT,
    WORKSHOP_SOURCE_IVR_NO_ANSWER,
    WORKSHOP_SOURCE_LINE,
    WORKSHOP_SOURCE_MULTIPLE,
    WORKSHOP_SOURCE_NO_MATCH,
    WORKSHOP_SOURCE_OPERATOR,
    WORKSHOP_SOURCE_RING_GROUP,
    CallRecord,
)
from app.models.department import Department
from app.models.workshop import Workshop
from app.models.workshop_phone_mapping import WorkshopPhoneMapping
from app.services import call_workshop_service
from app.services.call_workshop_service import (
    WorkshopIndex,
    determine_workshop,
    normalize_phone_or_line,
)

# ---- normalize_phone_or_line -----------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+79261537227", "79261537227"),
        ("89261537227", "79261537227"),
        ("9261537227", "79261537227"),
        ("8 (926) 153-72-27", "79261537227"),
        ("pan2", "pan2"),
        ("PAN2", "pan2"),
        ("0005348", "0005348"),  # 7 digits - not phone-shaped, kept literal
        ("2gis_moto", "2gis_moto"),
    ],
)
def test_normalize_phone_or_line(raw: str, expected: str) -> None:
    assert normalize_phone_or_line(raw) == expected


# ---- determine_workshop (pure decision logic, fake index) ------------------


class _FakeIndex:
    def __init__(self, by_phone: dict[str, set], by_extension: dict[str, set]) -> None:
        self._by_phone = by_phone
        self._by_extension = by_extension

    def phone_workshops(self, dst):
        return self._by_phone.get(normalize_phone_or_line(dst), set()) if dst else set()

    def extension_workshops(self, extension):
        return self._by_extension.get(extension.lower(), set()) if extension else set()


WS_A = uuid.uuid4()
WS_B = uuid.uuid4()


def test_inbound_matches_by_dst() -> None:
    index = _FakeIndex(by_phone={"pan2": {WS_A}}, by_extension={})
    workshop_id, source = determine_workshop(
        call_type=CALL_TYPE_IN, dst="pan2", exten=None, rang_extensions=None, index=index
    )
    assert (workshop_id, source) == (WS_A, WORKSHOP_SOURCE_LINE)


def test_inbound_falls_back_to_exten_when_dst_has_no_match() -> None:
    index = _FakeIndex(by_phone={}, by_extension={"302": {WS_B}})
    workshop_id, source = determine_workshop(
        call_type=CALL_TYPE_IN, dst="79261537227", exten="302", rang_extensions=None, index=index
    )
    assert (workshop_id, source) == (WS_B, WORKSHOP_SOURCE_OPERATOR)


def test_inbound_falls_back_to_ring_group_when_exten_empty() -> None:
    index = _FakeIndex(by_phone={}, by_extension={"302": {WS_A}})
    workshop_id, source = determine_workshop(
        call_type=CALL_TYPE_IN, dst=None, exten=None, rang_extensions=["302", "308"], index=index
    )
    assert (workshop_id, source) == (WS_A, WORKSHOP_SOURCE_RING_GROUP)


def test_inbound_dst_matching_multiple_workshops_is_undetermined() -> None:
    index = _FakeIndex(by_phone={"pan2": {WS_A, WS_B}}, by_extension={"302": {WS_A}})
    workshop_id, source = determine_workshop(
        call_type=CALL_TYPE_IN, dst="pan2", exten="302", rang_extensions=None, index=index
    )
    assert (workshop_id, source) == (None, WORKSHOP_SOURCE_MULTIPLE)


def test_inbound_ring_group_matching_multiple_workshops_is_undetermined() -> None:
    index = _FakeIndex(by_phone={}, by_extension={"302": {WS_A}, "308": {WS_B}})
    workshop_id, source = determine_workshop(
        call_type=CALL_TYPE_IN, dst=None, exten=None, rang_extensions=["302", "308"], index=index
    )
    assert (workshop_id, source) == (None, WORKSHOP_SOURCE_MULTIPLE)


def test_inbound_no_answer_and_no_match_anywhere_is_ivr_no_answer() -> None:
    """exten empty throughout (IVR self-service, per product spec point 1) -
    distinct from a genuine "we have no idea" no_match."""
    index = _FakeIndex(by_phone={}, by_extension={})
    workshop_id, source = determine_workshop(
        call_type=CALL_TYPE_IN, dst="79261537227", exten=None, rang_extensions=None, index=index
    )
    assert (workshop_id, source) == (None, WORKSHOP_SOURCE_IVR_NO_ANSWER)


def test_inbound_exten_set_but_unmatched_is_no_match_not_ivr() -> None:
    index = _FakeIndex(by_phone={}, by_extension={})
    workshop_id, source = determine_workshop(
        call_type=CALL_TYPE_IN, dst="79261537227", exten="999", rang_extensions=None, index=index
    )
    assert (workshop_id, source) == (None, WORKSHOP_SOURCE_NO_MATCH)


def test_outbound_matches_by_exten_only_ignores_dst() -> None:
    """dst for an OUT call is the external number dialed, never a цех
    signal - per the product spec's separate outbound rule."""
    index = _FakeIndex(by_phone={"79261537227": {WS_B}}, by_extension={"305": {WS_A}})
    workshop_id, source = determine_workshop(
        call_type=CALL_TYPE_OUT, dst="79261537227", exten="305", rang_extensions=None, index=index
    )
    assert (workshop_id, source) == (WS_A, WORKSHOP_SOURCE_OPERATOR)


def test_outbound_unmatched_exten_is_no_match() -> None:
    index = _FakeIndex(by_phone={}, by_extension={})
    workshop_id, source = determine_workshop(
        call_type=CALL_TYPE_OUT, dst="79261537227", exten="999", rang_extensions=None, index=index
    )
    assert (workshop_id, source) == (None, WORKSHOP_SOURCE_NO_MATCH)


# ---- WorkshopIndex + recompute_all (real DB) -------------------------------


@pytest.fixture()
def department(db_session: Session) -> Department:
    dept = Department(name="Каховка")
    db_session.add(dept)
    db_session.commit()
    return dept


def _make_workshop(db_session: Session, department: Department, workshop_type: str) -> Workshop:
    ws = Workshop(
        department_id=department.id,
        workshop_type=workshop_type,
        posts_count=2,
        start_time="08:00:00",
        end_time="20:00:00",
        working_days=[0, 1, 2, 3, 4],
    )
    db_session.add(ws)
    db_session.commit()
    return ws


def _make_call(db_session: Session, **overrides) -> CallRecord:
    defaults = dict(
        id=uuid.uuid4(),
        provider="zeon",
        external_id=str(uuid.uuid4()),
        call_date=datetime(2026, 9, 1, tzinfo=UTC).date(),
        occurred_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC),
        call_type=CALL_TYPE_IN,
    )
    defaults.update(overrides)
    call = CallRecord(**defaults)
    db_session.add(call)
    db_session.commit()
    return call


def test_workshop_index_groups_by_normalized_phone_and_lowercased_extension(
    db_session: Session, department: Department
) -> None:
    body = _make_workshop(db_session, department, "Кузовной")
    db_session.add(
        WorkshopPhoneMapping(workshop_id=body.id, phone="+7 926 153-72-27", extension=None)
    )
    db_session.add(WorkshopPhoneMapping(workshop_id=body.id, phone=None, extension="305"))
    db_session.commit()

    index = WorkshopIndex(db_session)

    assert index.phone_workshops("89261537227") == {body.id}
    assert index.extension_workshops("305") == {body.id}
    assert index.extension_workshops("999") == set()


def test_recompute_all_backfills_from_raw_payload_and_assigns_workshop(
    db_session: Session, department: Department
) -> None:
    mechanical = _make_workshop(db_session, department, "Слесарный")
    db_session.add(WorkshopPhoneMapping(workshop_id=mechanical.id, phone="pan2", extension=None))
    db_session.commit()

    # Imported before this feature existed - dst/exten/rang_extensions are
    # still NULL, only raw_payload has the original Zeon fields.
    call = _make_call(
        db_session,
        dst=None,
        exten=None,
        rang_extensions=None,
        raw_payload={"dst": "pan2", "exten": "", "members": "", "lost": ""},
    )

    processed = call_workshop_service.recompute_all(db_session)

    db_session.refresh(call)
    assert processed == 1
    assert call.dst == "pan2"
    assert call.exten is None
    assert call.workshop_id == mechanical.id
    assert call.workshop_source == WORKSHOP_SOURCE_LINE


def test_recompute_all_is_safe_to_rerun_after_mapping_changes(
    db_session: Session, department: Department
) -> None:
    body = _make_workshop(db_session, department, "Кузовной")
    mapping = WorkshopPhoneMapping(workshop_id=body.id, phone="pan2", extension=None)
    db_session.add(mapping)
    db_session.commit()

    call = _make_call(db_session, dst="pan2", exten="305", rang_extensions=None, raw_payload={})
    call_workshop_service.recompute_all(db_session)
    db_session.refresh(call)
    assert call.workshop_id == body.id

    # Mapping deleted - a re-run must un-assign the call, not leave it
    # pointing at a config that no longer exists.
    db_session.delete(mapping)
    db_session.commit()
    call_workshop_service.recompute_all(db_session)
    db_session.refresh(call)
    assert call.workshop_id is None
    # exten="305" matched nothing once the mapping was removed - a real
    # "we have no idea" case, not the IVR-specific "nobody ever answered".
    assert call.workshop_source == WORKSHOP_SOURCE_NO_MATCH
