"""Tests for services/call_transcription_service.py - the automatic,
per-call transcription + YandexGPT topic classification pipeline (see
services/call_transcription_relay.py for the background schedule that
drives this in production). No real network calls: zeon_client/
speechkit_client/yandexgpt_client are monkeypatched at the module level,
the same way test_yandexgpt_client.py mocks httpx.Client.post for that
client's own unit tests.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.call_record import (
    TOPIC_BODY,
    TRANSCRIPT_STATUS_CLASSIFIED,
    TRANSCRIPT_STATUS_FAILED,
    TRANSCRIPT_STATUS_TRANSCRIBED,
    CallRecord,
)
from app.models.telephony_settings import TelephonySettings
from app.services import call_transcription_service as svc
from app.services import speechkit_client, yandexgpt_client, zeon_client
from app.services.zeon_client import AudioFile, ZeonError

# MSK is UTC+3 - fixed "now" so find_pending_calls' today/yesterday window
# (see call_transcription_service.MAX_CALL_AGE_DAYS) is deterministic
# regardless of the real wall-clock date. _call()'s own default call_date
# below (2026-10-01) is "yesterday" relative to this.
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _settings(*, classify: bool = True) -> TelephonySettings:
    return TelephonySettings(
        id=1,
        zeon_api_url="https://zeon.example/api",
        zeon_api_key="zeon-key",
        zeon_auth="bearer",
        zeon_audio_method="get-mp3",
        yc_api_key="yc-key",
        yc_folder_id="folder-1",
        speechkit_model="general",
        speechkit_language="ru-RU",
        speechkit_timeout_min=1,
        classify_calls_enabled=classify,
        yandexgpt_model="yandexgpt-lite/latest",
    )


def _call(
    db_session: Session,
    *,
    link: str | None = "rec-link-1",
    talk_sec: int = 60,
    call_date: date = date(2026, 10, 1),
) -> CallRecord:
    call = CallRecord(
        id=uuid.uuid4(),
        provider="zeon",
        external_id=f"ext-{uuid.uuid4().hex[:8]}",
        call_date=call_date,
        occurred_at=datetime(call_date.year, call_date.month, call_date.day, 10, 0, tzinfo=UTC),
        call_type="IN",
        client="9990000001",
        operator="302",
        wait_sec=5,
        talk_sec=talk_sec,
        answered=talk_sec > 0,
        raw_payload={"link": link} if link is not None else {},
    )
    db_session.add(call)
    db_session.commit()
    db_session.refresh(call)
    return call


def _patch_happy_path(monkeypatch, *, topic: str = TOPIC_BODY) -> None:
    monkeypatch.setattr(
        zeon_client,
        "download_audio",
        lambda settings, link, method="get-mp3": AudioFile(
            data=b"x" * 2000, content_type="audio/mpeg", filename="call.mp3"
        ),
    )
    monkeypatch.setattr(
        speechkit_client, "submit", lambda client, settings, audio, container: "op-1"
    )
    monkeypatch.setattr(speechkit_client, "is_done", lambda client, settings, op_id: True)
    monkeypatch.setattr(
        speechkit_client, "get_result", lambda client, settings, op_id: [{"raw": True}]
    )
    monkeypatch.setattr(
        speechkit_client,
        "build_utterances",
        lambda responses: [{"speaker": "Говорящий 1", "text": "Нужна покраска бампера"}],
    )
    monkeypatch.setattr(yandexgpt_client, "classify_topic", lambda client, settings, text: topic)


def test_find_pending_calls_only_matches_answered_real_talk_zeon_calls(db_session: Session) -> None:
    real = _call(db_session, talk_sec=30)
    _call(db_session, talk_sec=0)  # missed - nothing to transcribe
    already_classified = _call(db_session, talk_sec=30)
    already_classified.transcript_status = TRANSCRIPT_STATUS_CLASSIFIED
    already_classified.topic_tag = TOPIC_BODY
    db_session.commit()

    pending = svc.find_pending_calls(db_session, limit=10, now=NOW)

    assert [c.id for c in pending] == [real.id]


def test_process_pending_calls_transcribes_and_classifies(monkeypatch, db_session: Session) -> None:
    call = _call(db_session)
    _patch_happy_path(monkeypatch, topic=TOPIC_BODY)

    stats = svc.process_pending_calls(db_session, _settings(classify=True), limit=10, now=NOW)

    assert stats.transcribed == 1
    assert stats.classified == 1
    assert stats.failed == 0
    assert stats.errors == 0

    db_session.refresh(call)
    assert call.transcript_status == TRANSCRIPT_STATUS_CLASSIFIED
    assert call.topic_tag == TOPIC_BODY
    assert call.transcript_text == "Говорящий 1: Нужна покраска бампера"
    assert call.transcript_error is None


def test_process_pending_calls_transcribes_only_when_classification_disabled(
    monkeypatch, db_session: Session
) -> None:
    call = _call(db_session)
    _patch_happy_path(monkeypatch)
    monkeypatch.setattr(
        yandexgpt_client,
        "classify_topic",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not be called")),
    )

    stats = svc.process_pending_calls(db_session, _settings(classify=False), limit=10, now=NOW)

    assert stats.transcribed == 1
    assert stats.classified == 0

    db_session.refresh(call)
    assert call.transcript_status == TRANSCRIPT_STATUS_TRANSCRIBED
    assert call.topic_tag is None


def test_process_pending_calls_marks_missing_link_as_failed(db_session: Session) -> None:
    call = _call(db_session, link=None)

    stats = svc.process_pending_calls(db_session, _settings(), limit=10, now=NOW)

    assert stats.failed == 1
    db_session.refresh(call)
    assert call.transcript_status == TRANSCRIPT_STATUS_FAILED
    assert call.transcript_error == "no recording link in raw_payload"


def test_process_pending_calls_marks_placeholder_recording_as_failed(
    monkeypatch, db_session: Session
) -> None:
    call = _call(db_session)
    monkeypatch.setattr(
        zeon_client,
        "download_audio",
        lambda settings, link, method="get-mp3": AudioFile(
            data=b"x" * 10, content_type="audio/mpeg", filename="call.mp3"
        ),
    )

    stats = svc.process_pending_calls(db_session, _settings(), limit=10, now=NOW)

    assert stats.failed == 1
    db_session.refresh(call)
    assert call.transcript_status == TRANSCRIPT_STATUS_FAILED
    assert call.transcript_error == "placeholder/empty recording"


def test_process_pending_calls_leaves_row_untouched_for_later_retry_on_download_error(
    monkeypatch, db_session: Session
) -> None:
    call = _call(db_session)

    def fail_download(settings, link, method="get-mp3"):
        raise ZeonError("boom")

    monkeypatch.setattr(zeon_client, "download_audio", fail_download)

    stats = svc.process_pending_calls(db_session, _settings(), limit=10, now=NOW)

    assert stats.errors == 1
    assert stats.failed == 0
    db_session.refresh(call)
    # Not "failed" - a transient error should be retried next cycle, not
    # parked permanently (see find_pending_calls: status still NULL here
    # still matches its own WHERE clause).
    assert call.transcript_status is None
    assert "boom" in (call.transcript_error or "")
    assert svc.find_pending_calls(db_session, limit=10, now=NOW) == [call]


def test_process_pending_calls_keeps_transcript_on_classification_failure(
    monkeypatch, db_session: Session
) -> None:
    call = _call(db_session)
    _patch_happy_path(monkeypatch)

    def fail_classify(client, settings, text):
        raise yandexgpt_client.YandexGPTError("rate limited")

    monkeypatch.setattr(yandexgpt_client, "classify_topic", fail_classify)

    stats = svc.process_pending_calls(db_session, _settings(classify=True), limit=10, now=NOW)

    assert stats.transcribed == 1
    assert stats.errors == 1
    db_session.refresh(call)
    # Transcript stays saved - a later cycle only has to retry
    # classification, not re-pay for SpeechKit too.
    assert call.transcript_status == TRANSCRIPT_STATUS_TRANSCRIBED
    assert call.transcript_text
    assert call.topic_tag is None


def test_process_pending_calls_respects_limit(monkeypatch, db_session: Session) -> None:
    for _ in range(3):
        _call(db_session)
    _patch_happy_path(monkeypatch)

    stats = svc.process_pending_calls(db_session, _settings(classify=True), limit=2, now=NOW)

    assert stats.transcribed == 2


def test_process_pending_calls_noop_when_nothing_pending(db_session: Session) -> None:
    stats = svc.process_pending_calls(db_session, _settings(), limit=10, now=NOW)
    assert stats == svc.ProcessStats()


def test_find_pending_calls_excludes_calls_older_than_yesterday(db_session: Session) -> None:
    """Product ask, 2026-10-02: "не дёргал звонки старше 2 дней (вчера и
    сегодня)... старше уже не актуально"."""
    today = _call(db_session, call_date=NOW.date())
    yesterday = _call(db_session, call_date=NOW.date() - timedelta(days=1))
    _call(db_session, call_date=NOW.date() - timedelta(days=2))  # too old - excluded

    pending = svc.find_pending_calls(db_session, limit=10, now=NOW)

    assert {c.id for c in pending} == {today.id, yesterday.id}


def test_process_pending_calls_raises_when_zeon_not_configured(db_session: Session) -> None:
    _call(db_session)
    settings = _settings()
    settings.zeon_api_url = None

    with pytest.raises(svc.CallTranscriptionError):
        svc.process_pending_calls(db_session, settings, limit=10, now=NOW)
