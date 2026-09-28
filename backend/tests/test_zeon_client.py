"""Tests for services/zeon_client.py's pure helpers - request signing and
call normalization - ported from Zeon_AI/zeon_to_yadisk.py and stats.py.
No network/DB involved; see test_telephony_stats.py for the DB-backed
stats logic these normalized calls feed into.
"""

import hashlib
from datetime import UTC, datetime

import pytest

from app.services.zeon_client import (
    ZeonError,
    ZeonSettings,
    _build_request,
    _normalize_calls,
    _parse_duration,
    _php_http_build_query,
    _zeon_sign,
)


def test_php_http_build_query_matches_php_conventions() -> None:
    query = _php_http_build_query({"topic": "base", "method": "get-calls", "limit": 0})
    assert query == "topic=base&method=get-calls&limit=0"


def test_php_http_build_query_encodes_spaces_as_plus() -> None:
    query = _php_http_build_query({"start": "2026-09-20 00:00:00"})
    assert query == "start=2026-09-20+00%3A00%3A00"


def test_zeon_sign_is_md5_of_query_plus_key() -> None:
    query = "topic=base&method=ping"
    key = "secret"
    assert _zeon_sign(query, key) == hashlib.md5((query + key).encode("utf-8")).hexdigest()


def test_build_request_uses_bearer_header_for_https() -> None:
    settings = ZeonSettings(
        api_url="https://z138.fpg.ru/zeon/api/v2/start.php", api_key="tok", auth="bearer"
    )
    body, headers = _build_request(settings, "ping", {})
    assert headers["Authorization"] == "Bearer tok"
    assert "hash=" not in body


def test_build_request_appends_hash_for_hash_auth() -> None:
    settings = ZeonSettings(
        api_url="http://z138.fpg.ru/zeon/api/v2/start.php", api_key="tok", auth="hash"
    )
    body, headers = _build_request(settings, "ping", {})
    assert "Authorization" not in headers
    assert "&hash=" in body


def test_build_request_rejects_bearer_over_plain_http() -> None:
    settings = ZeonSettings(
        api_url="http://z138.fpg.ru/zeon/api/v2/start.php", api_key="tok", auth="bearer"
    )
    with pytest.raises(ZeonError):
        _build_request(settings, "ping", {})


def test_parse_duration_accepts_hms_and_plain_seconds() -> None:
    assert _parse_duration("00:01:05") == 65
    assert _parse_duration("42") == 42
    assert _parse_duration(None) == 0
    assert _parse_duration("") == 0


def test_normalize_calls_classifies_inbound_and_outbound() -> None:
    raw = [
        {
            "id": "1001",
            "linkedid": "l1001",
            "calldate": "2026-09-20 10:00:00",
            "calltype": "IN",
            "src": "79991234567",
            "dst": "pan",
            "client": None,
            "exten": "302",
            "members": "302",
            "lost": "",
            "waiting": "5",
            "talktime": "60",
            "link": "",
        },
        {
            "id": "1002",
            "linkedid": "l1002",
            "calldate": "2026-09-20 11:00:00",
            "calltype": "OUT",
            "src": "302",
            "dst": "79991234567",
            "client": None,
            "exten": "302",
            "members": "",
            "lost": "",
            "waiting": "0",
            "talktime": "0",
            "link": "",
        },
    ]
    calls = _normalize_calls(raw)
    assert len(calls) == 2

    inbound, outbound = calls
    assert inbound.call_type == "IN"
    assert inbound.client == "9991234567"
    assert inbound.line == "pan"
    assert inbound.operator == "302"
    assert inbound.answered is True
    assert inbound.occurred_at == datetime(2026, 9, 20, 7, 0, 0, tzinfo=UTC)

    assert outbound.call_type == "OUT"
    assert outbound.client == "9991234567"
    assert outbound.line is None
    assert outbound.answered is False


def test_normalize_calls_handles_dict_keyed_response() -> None:
    raw = {
        "1001": {
            "id": "1001",
            "linkedid": "l1001",
            "calldate": "2026-09-20 10:00:00",
            "calltype": "IN",
            "src": "9991234567",
            "dst": "pan",
            "exten": "302",
            "members": "302",
            "waiting": "5",
            "talktime": "60",
        }
    }
    calls = _normalize_calls(raw)
    assert len(calls) == 1
    assert calls[0].external_id == "1001"


def test_normalize_calls_empty_input() -> None:
    assert _normalize_calls(None) == []
    assert _normalize_calls([]) == []
    assert _normalize_calls({}) == []
