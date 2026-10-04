"""Tests for services/telephony_import_service.py - the upsert path from
zeon_client.NormalizedCall into telephony_calls, including the цех
determination now folded into it (see services/call_workshop_service.py)."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.models.call_record import CALL_TYPE_IN, CALL_TYPE_OUT, CallRecord
from app.models.department import Department
from app.models.workshop import Workshop
from app.models.workshop_phone_mapping import WorkshopPhoneMapping
from app.services.telephony_import_service import _upsert_calls
from app.services.zeon_client import NormalizedCall


def _normalized(**overrides) -> NormalizedCall:
    defaults = dict(
        external_id="ext-1",
        linkedid="link-1",
        call_date_iso="2026-09-01",
        occurred_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC),
        call_type=CALL_TYPE_IN,
        client="9991234567",
        line="pan2",
        operator="305",
        rang_not_answered=[],
        wait_sec=5,
        talk_sec=30,
        answered=True,
        raw={},
        dst="pan2",
        exten="305",
        rang_extensions=["305"],
    )
    defaults.update(overrides)
    return NormalizedCall(**defaults)


def _make_workshop(db_session, workshop_type: str = "Слесарный") -> Workshop:
    department = Department(name="Каховка")
    db_session.add(department)
    db_session.commit()
    workshop = Workshop(
        department_id=department.id,
        workshop_type=workshop_type,
        posts_count=2,
        start_time="08:00:00",
        end_time="20:00:00",
        working_days=[0, 1, 2, 3, 4],
    )
    db_session.add(workshop)
    db_session.commit()
    return workshop


def test_upsert_calls_assigns_workshop_on_first_import(db_session) -> None:
    workshop = _make_workshop(db_session)
    db_session.add(WorkshopPhoneMapping(workshop_id=workshop.id, phone="pan2", extension=None))
    db_session.commit()

    _upsert_calls(db_session, "zeon", [_normalized()])

    call = db_session.scalars(select(CallRecord).where(CallRecord.external_id == "ext-1")).one()
    assert call.dst == "pan2"
    assert call.exten == "305"
    assert call.rang_extensions == ["305"]
    assert call.workshop_id == workshop.id
    assert call.workshop_source == "line"


def test_upsert_calls_is_idempotent_by_external_id(db_session) -> None:
    workshop = _make_workshop(db_session)
    db_session.add(WorkshopPhoneMapping(workshop_id=workshop.id, phone="pan2", extension=None))
    db_session.commit()

    _upsert_calls(db_session, "zeon", [_normalized()])
    _upsert_calls(db_session, "zeon", [_normalized(talk_sec=999)])  # re-deliver, changed field

    calls = list(db_session.scalars(select(CallRecord).where(CallRecord.external_id == "ext-1")))
    assert len(calls) == 1
    assert calls[0].talk_sec == 999


def test_upsert_calls_outbound_matches_by_exten_not_dst(db_session) -> None:
    workshop = _make_workshop(db_session, "Кузовной")
    db_session.add(WorkshopPhoneMapping(workshop_id=workshop.id, phone=None, extension="305"))
    db_session.commit()

    _upsert_calls(
        db_session,
        "zeon",
        [
            _normalized(
                external_id="ext-out",
                call_type=CALL_TYPE_OUT,
                dst="79991234567",  # the external number dialed - not a цех signal
                exten="305",
                rang_extensions=[],
                line=None,
            )
        ],
    )

    call = db_session.scalars(select(CallRecord).where(CallRecord.external_id == "ext-out")).one()
    assert call.workshop_id == workshop.id
    assert call.workshop_source == "operator"


def test_upsert_calls_without_any_mapping_leaves_workshop_unset(db_session) -> None:
    _upsert_calls(db_session, "zeon", [_normalized(external_id="ext-nomap")])

    call = db_session.scalars(select(CallRecord).where(CallRecord.external_id == "ext-nomap")).one()
    assert call.workshop_id is None
    assert call.workshop_source == "no_match"
