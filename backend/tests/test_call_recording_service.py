"""Tests for services/call_recording_service.py's live PLAY-button fetch
(recording_link/fetch_recording) - the export/transcribe pipeline above
these two already has its own coverage elsewhere; these focus on what's
new (product ask, 2026-10-21).
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.models.call_record import CallRecord
from app.models.telephony_settings import TelephonySettings
from app.services import call_recording_service
from app.services.zeon_client import AudioFile, ZeonError


def _call(raw_payload: dict | None) -> CallRecord:
    return CallRecord(
        id=uuid.uuid4(),
        provider="zeon",
        external_id="1",
        call_date=datetime(2026, 10, 1, tzinfo=UTC).date(),
        occurred_at=datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC),
        call_type="IN",
        raw_payload=raw_payload,
    )


def _settings(**overrides) -> TelephonySettings:
    defaults = dict(
        id=1,
        zeon_api_url="https://pbx.example/api",
        zeon_api_key="key",
        zeon_auth="bearer",
        zeon_audio_method="get-mp3",
    )
    defaults.update(overrides)
    return TelephonySettings(**defaults)


# ---- recording_link ----------------------------------------------------


@pytest.mark.parametrize(
    "raw_payload",
    [None, {}, {"link": ""}, {"link": "0"}, {"link": "   "}],
)
def test_recording_link_none_without_a_real_link(raw_payload) -> None:
    assert call_recording_service.recording_link(_call(raw_payload)) is None


def test_recording_link_returns_the_zeon_reference() -> None:
    assert call_recording_service.recording_link(_call({"link": "abc123"})) == "abc123"


# ---- fetch_recording -----------------------------------------------------


def test_fetch_recording_raises_without_a_link() -> None:
    with pytest.raises(call_recording_service.CallRecordingError, match="no recording"):
        call_recording_service.fetch_recording(_settings(), _call(None))


def test_fetch_recording_raises_when_zeon_not_configured() -> None:
    call = _call({"link": "abc123"})
    with pytest.raises(call_recording_service.CallRecordingError, match="not configured"):
        call_recording_service.fetch_recording(_settings(zeon_api_url=None), call)


def test_fetch_recording_returns_zeon_audio_file(monkeypatch) -> None:
    call = _call({"link": "abc123"})
    audio = AudioFile(data=b"fake-mp3-bytes", content_type="audio/mpeg", filename=None)

    captured = {}

    def fake_download_audio(zeon_settings, link, method):
        captured["link"] = link
        captured["method"] = method
        return audio

    monkeypatch.setattr(call_recording_service.zeon_client, "download_audio", fake_download_audio)

    result = call_recording_service.fetch_recording(_settings(), call)

    assert result is audio
    assert captured == {"link": "abc123", "method": "get-mp3"}


def test_fetch_recording_wraps_zeon_errors(monkeypatch) -> None:
    call = _call({"link": "abc123"})

    def fake_download_audio(zeon_settings, link, method):
        raise ZeonError("boom")

    monkeypatch.setattr(call_recording_service.zeon_client, "download_audio", fake_download_audio)

    with pytest.raises(call_recording_service.CallRecordingError, match="boom"):
        call_recording_service.fetch_recording(_settings(), call)
