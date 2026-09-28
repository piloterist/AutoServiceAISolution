"""Yandex SpeechKit v3 async speech recognition client - the transcription
half of services/call_recording_service.py's export+transcribe pipeline.

Ported from Zeon_AI/transcribe.py's `SpeechKit` class and result-assembly
helpers (build_utterances/build_document), reshaped onto httpx instead of
`requests` - same submit -> poll -> fetch-result shape, since that's how
SpeechKit's async recognition API itself works (there's no synchronous
"just give me the text" call for anything but very short audio).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx

STT_URL = "https://stt.api.cloud.yandex.net/stt/v3"
OPERATIONS_URL = "https://operation.api.cloud.yandex.net/operations"
REQUEST_TIMEOUT_SECONDS = 60.0

SCHEMA = "zeon-call-transcript/1"

# Same fixed-offset duplication as the other telephony modules - Russia has
# used a flat UTC+3 with no DST since 2014.
_MSK = timezone(timedelta(hours=3))


class SpeechKitError(Exception):
    """Raised on any SpeechKit or operation-polling failure."""


@dataclass
class SpeechKitSettings:
    api_key: str
    folder_id: str | None
    model: str = "general"
    language: str = "ru-RU"


def _headers(settings: SpeechKitSettings) -> dict[str, str]:
    headers = {"Authorization": f"Api-Key {settings.api_key}"}
    if settings.folder_id:
        headers["x-folder-id"] = settings.folder_id
    return headers


def _request_body(settings: SpeechKitSettings, audio: bytes, container: str) -> dict:
    return {
        "content": base64.b64encode(audio).decode("ascii"),
        "recognitionModel": {
            "model": settings.model,
            "audioFormat": {"containerAudio": {"containerAudioType": container}},
            "textNormalization": {
                "textNormalization": "TEXT_NORMALIZATION_ENABLED",
                "profanityFilter": False,
                "literatureText": True,
            },
            "languageRestriction": {
                "restrictionType": "WHITELIST",
                "languageCode": [settings.language],
            },
        },
        "speakerLabeling": {"speakerLabeling": "SPEAKER_LABELING_ENABLED"},
    }


def _error(response: httpx.Response, what: str) -> SpeechKitError:
    try:
        info = response.json()
        detail = info.get("message") or info.get("error") or info
    except ValueError:
        detail = response.text[:300]
    return SpeechKitError(f"{what}: HTTP {response.status_code} {detail}")


def submit(
    client: httpx.Client, settings: SpeechKitSettings, audio: bytes, container: str = "MP3"
) -> str:
    """Submits a recording for async recognition, returns the operation id."""
    try:
        response = client.post(
            f"{STT_URL}/recognizeFileAsync",
            json=_request_body(settings, audio, container),
            headers=_headers(settings),
        )
    except httpx.HTTPError as exc:
        raise SpeechKitError(f"recognizeFileAsync failed: {exc}") from exc
    if response.status_code != 200:
        raise _error(response, "recognizeFileAsync")
    op_id = response.json().get("id")
    if not op_id:
        raise SpeechKitError(
            f"recognizeFileAsync: no operation id in response: {response.text[:200]}"
        )
    return op_id


def is_done(client: httpx.Client, settings: SpeechKitSettings, op_id: str) -> bool:
    try:
        response = client.get(f"{OPERATIONS_URL}/{op_id}", headers=_headers(settings))
    except httpx.HTTPError as exc:
        raise SpeechKitError(f"operation {op_id} status check failed: {exc}") from exc
    if response.status_code != 200:
        raise _error(response, f"operation {op_id}")
    operation = response.json()
    if operation.get("error"):
        err = operation["error"]
        raise SpeechKitError(f"operation {op_id}: {err.get('message') or err}")
    return bool(operation.get("done"))


def _parse_responses(text: str) -> list[dict]:
    """getRecognition streams one JSON object per line, sometimes wrapped
    in {"result": ...}."""
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        items = data if isinstance(data, list) else [data]
    except ValueError:
        items = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [item.get("result", item) if isinstance(item, dict) else item for item in items]


def get_result(client: httpx.Client, settings: SpeechKitSettings, op_id: str) -> list[dict]:
    try:
        response = client.get(
            f"{STT_URL}/getRecognition", params={"operationId": op_id}, headers=_headers(settings)
        )
    except httpx.HTTPError as exc:
        raise SpeechKitError(f"getRecognition {op_id} failed: {exc}") from exc
    if response.status_code != 200:
        raise _error(response, f"getRecognition {op_id}")
    return _parse_responses(response.text)


def _first_alternative(block: Mapping[str, Any] | None) -> dict:
    alts = (block or {}).get("alternatives") or []
    return alts[0] if alts else {}


def build_utterances(responses: Iterable[Mapping[str, Any]]) -> list[dict]:
    """One row per speech segment, text preferring `finalRefinement`
    (punctuated) over the raw `final` event when both exist for the same
    segment."""
    finals: dict[tuple[str, str], dict] = {}
    refined: dict[tuple[str, str], str] = {}
    for n, resp in enumerate(responses):
        channel = str(resp.get("channelTag", "0"))
        if "final" in resp:
            alt = _first_alternative(resp["final"])
            index = str((resp.get("audioCursors") or {}).get("finalIndex", f"#{n}"))
            if alt.get("text", "").strip():
                finals[(channel, index)] = {
                    "channel": channel,
                    "start_ms": int(alt.get("startTimeMs") or 0),
                    "end_ms": int(alt.get("endTimeMs") or 0),
                    "text": alt["text"].strip(),
                }
        elif "finalRefinement" in resp:
            fr = resp["finalRefinement"]
            alt = _first_alternative(fr.get("normalizedText"))
            if alt.get("text", "").strip():
                refined[(channel, str(fr.get("finalIndex")))] = alt["text"].strip()

    utterances = []
    for key, utt in finals.items():
        if key in refined:
            utt["text"] = refined[key]
        utterances.append(utt)
    utterances.sort(key=lambda u: (u["start_ms"], u["channel"]))

    speakers: dict[str, str] = {}
    for utt in utterances:
        utt["speaker"] = speakers.setdefault(utt.pop("channel"), f"Говорящий {len(speakers) + 1}")
    return utterances


def fmt_ts(ms: int) -> str:
    sec = ms // 1000
    h, rem = divmod(sec, 3600)
    return f"{h:d}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60:02d}:{rem % 60:02d}"


def build_document(
    *,
    call: dict,
    audio_path: str,
    audio_size: int,
    settings: SpeechKitSettings,
    op_id: str,
    utterances: list[dict],
) -> dict:
    lines = [f"[{fmt_ts(u['start_ms'])}] {u['speaker']}: {u['text']}" for u in utterances]
    return {
        "schema": SCHEMA,
        "call": call,
        "audio": {
            "path": audio_path,
            "size_bytes": audio_size,
            "speech_end_sec": round(max((u["end_ms"] for u in utterances), default=0) / 1000, 1),
        },
        "transcription": {
            "engine": "yandex-speechkit-v3",
            "model": settings.model,
            "language": settings.language,
            "speaker_labeling": True,
            "operation_id": op_id,
            "created_at": datetime.now(UTC).astimezone(_MSK).isoformat(timespec="seconds"),
            "note": (
                "Метки «Говорящий N» проставлены автоматически по голосу; кто из них оператор, "
                "а кто клиент, SpeechKit не определяет."
            ),
        },
        "speakers": sorted({u["speaker"] for u in utterances}),
        "utterances": [
            {
                "start": fmt_ts(u["start_ms"]),
                "start_ms": u["start_ms"],
                "end_ms": u["end_ms"],
                "speaker": u["speaker"],
                "text": u["text"],
            }
            for u in utterances
        ],
        "text": "\n".join(lines),
    }


def new_client() -> httpx.Client:
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
