"""IP-телефония connector: Zeon (IP-АТС) call log API.

Ported from the standalone `Zeon_AI/zeon_to_yadisk.py` proof-of-concept
(request signing, call-log field parsing) rather than re-derived, but
reshaped to this backend's own conventions: a sync `httpx.Client` module
(same style as services/fivesystems_client.py, not the standalone script's
`requests`), and settings passed in explicitly (from
models/telephony_settings.py, editable in Settings -> IP-телефония) rather
than read from env vars - the whole point of that settings table is that
these values are operator-editable without a redeploy.

Also covers recording download (`get-mp3`/`get-file`, see download_audio())
for services/call_recording_service.py's export+transcribe pipeline - the
call *log* fetch above (fetch_calls) is what the stats page runs on, this
is a separate, much larger payload only fetched for calls actually being
exported.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

REQUEST_TIMEOUT_SECONDS = 60.0
# Recordings can run a few MB for a long call - same reasoning as Zeon_AI's
# own TIMEOUT_FILE (10s connect, 300s read) collapsed to one generous value
# (httpx.Client(timeout=...) is a single float here, not a per-phase tuple).
AUDIO_REQUEST_TIMEOUT_SECONDS = 180.0
ZEON_DT_FORMAT = "%Y-%m-%d %H:%M:%S"

_EXT_BY_CONTENT_TYPE = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
}

CALL_TYPE_IN = "IN"
CALL_TYPE_OUT = "OUT"

# Zeon's own clock is Russia's, which has used a flat UTC+3 with no DST
# since 2014 - same reasoning/constant as import_service._naive_msk_to_utc,
# duplicated rather than imported since that one is a private helper of an
# unrelated service module.
_MSK = timezone(timedelta(hours=3))


class ZeonError(Exception):
    """Raised when Zeon can't be reached, rejects the request, or returns
    something this connector doesn't know how to use."""


def _msk_naive_to_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    return value.replace(tzinfo=_MSK).astimezone(UTC)


def _php_urlencode(value: Any) -> str:
    # PHP urlencode(): space -> '+', only [A-Za-z0-9_.-] left unescaped.
    # Python's quote_plus leaves '~' alone; PHP escapes it to %7E.
    return quote_plus(str(value), safe="").replace("~", "%7E")


def _php_http_build_query(params: Mapping[str, Any]) -> str:
    """PHP's http_build_query() (PHP_QUERY_RFC1738) - Zeon's request
    signing (see _zeon_sign) is defined against this exact encoding, not
    Python's own query-string conventions."""
    parts = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = int(value)
        parts.append(f"{_php_urlencode(key)}={_php_urlencode(value)}")
    return "&".join(parts)


def _zeon_sign(query: str, api_key: str) -> str:
    """hash = md5(http_build_query(params) . api_key) - Zeon's ZEON_AUTH=hash
    mode (an alternative to Bearer for non-https endpoints)."""
    return hashlib.md5((query + api_key).encode("utf-8")).hexdigest()


def _norm_phone(value: Any) -> str:
    """Last 10 digits - Zeon mixes 79.../9... formats for the same number."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else digits


def _split_exts(value: Any) -> list[str]:
    return [p for p in re.split(r"[:,;\s]+", str(value or "")) if p]


def _parse_calldate(value: Any) -> datetime:
    text = str(value or "").strip()
    for fmt in (ZEON_DT_FORMAT, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError(f"Zeon: could not parse calldate={value!r}")


def _parse_duration(value: Any) -> int:
    """talktime/waiting come as "ЧЧ:ММ:СС" in practice, sometimes a plain
    number of seconds. Unparsable -> 0, never fails the whole call."""
    text = str(value if value is not None else "").strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    m = re.fullmatch(r"(\d+):(\d{1,2}):(\d{1,2})", text)
    if m:
        h, mnt, s = map(int, m.groups())
        return h * 3600 + mnt * 60 + s
    return 0


@dataclass
class ZeonSettings:
    """The subset of models.telephony_settings.TelephonySettings this
    client needs - kept as its own small type so callers don't have to
    pass the ORM row (or a DB session) into a pure API-client module."""

    api_url: str
    api_key: str
    auth: str = "bearer"  # "bearer" or "hash" - see models/telephony_settings.py


@dataclass
class NormalizedCall:
    """One call, already reshaped into models.call_record.CallRecord's own
    field names - see that module's docstring on why upsert is keyed by
    (provider, external_id) rather than any file/batch bookkeeping.

    external_id is Zeon's own `id` (one per returned call record - this is
    what Zeon_AI/stats.py itself uses to uniquely match a call, e.g. for
    "is this OUT call a callback to a missed IN call"), not `linkedid`
    (which only groups related legs and can repeat across distinct call
    records)."""

    external_id: str
    linkedid: str | None
    call_date_iso: str  # Moscow-local calendar day, "YYYY-MM-DD"
    occurred_at: datetime  # UTC
    call_type: str
    client: str | None
    line: str | None
    operator: str | None
    rang_not_answered: list[str]
    wait_sec: int
    talk_sec: int
    answered: bool
    raw: dict


def _build_request(
    settings: ZeonSettings, method: str, params: Mapping[str, Any]
) -> tuple[str, dict[str, str]]:
    auth = settings.auth.lower()
    if auth not in ("bearer", "hash"):
        raise ZeonError(f"Unsupported Zeon auth mode {settings.auth!r} (expected bearer or hash)")
    if auth == "bearer" and not settings.api_url.lower().startswith("https://"):
        raise ZeonError("Zeon Bearer auth requires an https:// API URL (or switch to hash auth)")

    payload: dict[str, Any] = {"topic": "base", "method": method, **params}
    body = _php_http_build_query(payload)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if auth == "hash":
        body += "&hash=" + _zeon_sign(body, settings.api_key)
    else:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    return body, headers


def _call_json(
    settings: ZeonSettings, method: str, params: Mapping[str, Any] | None = None
) -> dict:
    body, headers = _build_request(settings, method, params or {})
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.post(settings.api_url, content=body.encode("utf-8"), headers=headers)
    except httpx.HTTPError as exc:
        raise ZeonError(f"Zeon {method} request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise ZeonError(
            f"Zeon {method}: HTTP {response.status_code}, "
            f"expected JSON, got {response.text[:200]!r}"
        ) from exc
    if not isinstance(data, dict):
        raise ZeonError(f"Zeon {method}: unexpected response shape: {str(data)[:200]}")
    if str(data.get("result")) != "1":
        raise ZeonError(f"Zeon {method}: result={data.get('result')!r}, text={data.get('text')!r}")
    return data


def ping(settings: ZeonSettings) -> None:
    """Raises ZeonError if the connection/credentials don't work - used by
    the "Проверить соединение" button in Settings -> IP-телефония. Returns
    nothing on success; the caller only needs to know it didn't raise."""
    _call_json(settings, "ping")


def _normalize_one(raw: Mapping[str, Any]) -> NormalizedCall | None:
    call_type = str(raw.get("calltype") or "")
    members = _split_exts(raw.get("members"))
    exten = str(raw.get("exten") or "")

    if call_type == CALL_TYPE_IN:
        client = _norm_phone(raw.get("client") or raw.get("src"))
        operator = members[0] if members else exten
        line = str(raw.get("dst") or "") or None
    elif call_type == CALL_TYPE_OUT:
        client = _norm_phone(raw.get("client") or raw.get("dst"))
        operator = exten or str(raw.get("src") or "")
        line = None
    else:
        client, operator, line = None, exten or (members[0] if members else None), None

    try:
        local_dt = _parse_calldate(raw.get("calldate"))
    except ValueError:
        return None

    talk = _parse_duration(raw.get("talktime"))
    linkedid = str(raw.get("linkedid") or "") or None
    return NormalizedCall(
        external_id=str(raw.get("id") or linkedid or ""),
        linkedid=linkedid,
        call_date_iso=local_dt.date().isoformat(),
        occurred_at=_msk_naive_to_utc(local_dt),
        call_type=call_type or "UNKNOWN",
        client=client or None,
        line=line,
        operator=operator or None,
        rang_not_answered=_split_exts(raw.get("lost")),
        wait_sec=_parse_duration(raw.get("waiting")),
        talk_sec=talk,
        answered=talk > 0,
        raw=dict(raw),
    )


def _normalize_calls(raw: Any) -> list[NormalizedCall]:
    if raw in (None, "", [], {}):
        return []
    if isinstance(raw, dict):
        items = [raw] if "linkedid" in raw or "calldate" in raw else list(raw.values())
    elif isinstance(raw, list):
        items = raw
    else:
        raise ZeonError(f"Zeon get-calls: unexpected data shape: {type(raw).__name__}")

    calls = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_one(item)
        if normalized is not None and normalized.external_id:
            calls.append(normalized)
    return calls


def fetch_calls(settings: ZeonSettings, start: datetime, end: datetime) -> list[NormalizedCall]:
    """Calls for [start, end], both naive Moscow-local timestamps (Zeon's
    own convention) - see services/telephony_import_service.py for how the
    window is chosen."""
    data = _call_json(
        settings,
        "get-calls",
        {
            "start": start.strftime(ZEON_DT_FORMAT),
            "end": end.strftime(ZEON_DT_FORMAT),
            "limit": 0,
            "disposition": "any",
        },
    )
    return _normalize_calls(data.get("data"))


@dataclass
class AudioFile:
    data: bytes
    content_type: str
    filename: str | None

    @property
    def ext(self) -> str:
        if self.content_type in _EXT_BY_CONTENT_TYPE:
            return _EXT_BY_CONTENT_TYPE[self.content_type]
        if self.filename and "." in self.filename:
            return "." + self.filename.rsplit(".", 1)[1].lower()
        return ".mp3"


def _parse_content_disposition(value: str | None) -> str | None:
    if not value:
        return None
    m = re.search(r"filename\*?\s*=\s*(?:UTF-8'')?\"?([^\";]+)\"?", value, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _raise_not_audio(method: str, response: httpx.Response, ctype: str) -> None:
    text = response.text
    try:
        data = json.loads(text)
    except ValueError:
        raise ZeonError(
            f"Zeon {method}: HTTP {response.status_code}, expected audio, "
            f"got {ctype or 'no content-type'}: {text[:200]!r}"
        ) from None
    if isinstance(data, dict):
        raise ZeonError(
            f"Zeon {method}: got JSON instead of audio: "
            f"result={data.get('result')!r}, text={data.get('text')!r}"
        )
    raise ZeonError(f"Zeon {method}: got JSON instead of audio: {text[:200]!r}")


def download_audio(settings: ZeonSettings, link: str, method: str = "get-mp3") -> AudioFile:
    """Downloads one call recording (`get-mp3` or `get-file`) - `link` is
    Zeon's own recording reference (the `link` field on a get-calls row,
    not a URL). See services/call_recording_service.py, which pulls it out
    of CallRecord.raw_payload rather than a dedicated column, since nothing
    needed it before this pipeline."""
    if method not in ("get-mp3", "get-file"):
        raise ZeonError(f"Unsupported Zeon audio method {method!r} (expected get-mp3 or get-file)")

    body, headers = _build_request(settings, method, {"link": link})
    try:
        with httpx.Client(timeout=AUDIO_REQUEST_TIMEOUT_SECONDS) as client:
            response = client.post(settings.api_url, content=body.encode("utf-8"), headers=headers)
    except httpx.HTTPError as exc:
        raise ZeonError(f"Zeon {method} link={link} failed: {exc}") from exc

    ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype == "application/json" or ctype.startswith("text/") or response.status_code != 200:
        _raise_not_audio(method, response, ctype)
    if not (ctype.startswith("audio/") or ctype == "application/octet-stream"):
        raise ZeonError(f"Zeon {method}: unexpected Content-Type {ctype!r}")

    data = response.content
    if not data:
        raise ZeonError(f"Zeon {method}: empty file")
    return AudioFile(
        data=data,
        content_type=ctype,
        filename=_parse_content_disposition(response.headers.get("content-disposition")),
    )
