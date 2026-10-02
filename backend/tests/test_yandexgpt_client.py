"""Tests for services/yandexgpt_client.py - the call-topic classification
client (Yandex Foundation Models). No real network calls - httpx.Client.post
is monkeypatched per test, same approach as test_speechkit_client.py would
use for the sibling SpeechKit client.
"""

import httpx
import pytest

from app.services.yandexgpt_client import (
    TOPIC_BODY,
    TOPIC_MECHANICAL,
    TOPIC_UNKNOWN,
    YandexGPTError,
    YandexGPTSettings,
    classify_topic,
)

SETTINGS = YandexGPTSettings(
    api_key="test-key", folder_id="folder-1", model="yandexgpt-lite/latest"
)


def _completion_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"result": {"alternatives": [{"message": {"role": "assistant", "text": text}}]}},
        request=httpx.Request(
            "POST", "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        ),
    )


def test_classify_topic_sends_expected_request_shape(monkeypatch) -> None:
    captured = {}

    def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _completion_response("Кузовной")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    with httpx.Client() as client:
        result = classify_topic(client, SETTINGS, "Клиент: нужна покраска бампера после удара")

    assert result == TOPIC_BODY
    assert captured["url"] == "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    assert captured["headers"]["Authorization"] == "Api-Key test-key"
    assert captured["headers"]["x-folder-id"] == "folder-1"
    assert captured["json"]["modelUri"] == "gpt://folder-1/yandexgpt-lite/latest"
    assert captured["json"]["messages"][1]["text"].startswith("Клиент: нужна покраска")


@pytest.mark.parametrize(
    ("raw_answer", "expected"),
    [
        ("Кузовной", TOPIC_BODY),
        ("кузовной", TOPIC_BODY),
        ("Кузовной.", TOPIC_BODY),
        ("Слесарный", TOPIC_MECHANICAL),
        ("Слесарный ремонт", TOPIC_MECHANICAL),
        ("Не определено", TOPIC_UNKNOWN),
        ("не знаю, непонятно", TOPIC_UNKNOWN),
        ("", TOPIC_UNKNOWN),
    ],
)
def test_classify_topic_parses_model_answer(monkeypatch, raw_answer, expected) -> None:
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, json=None, headers=None: _completion_response(raw_answer),
    )
    with httpx.Client() as client:
        assert classify_topic(client, SETTINGS, "любой текст") == expected


def test_classify_topic_empty_transcript_returns_unknown_without_request(monkeypatch) -> None:
    def fail_post(self, *a, **kw):  # noqa: ANN001
        raise AssertionError("should not call the API for an empty transcript")

    monkeypatch.setattr(httpx.Client, "post", fail_post)
    with httpx.Client() as client:
        assert classify_topic(client, SETTINGS, "   ") == TOPIC_UNKNOWN


def test_classify_topic_raises_on_http_error(monkeypatch) -> None:
    def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
        return httpx.Response(
            401, json={"message": "Unauthorized"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with httpx.Client() as client, pytest.raises(YandexGPTError):
        classify_topic(client, SETTINGS, "текст")


def test_classify_topic_raises_on_unexpected_response_shape(monkeypatch) -> None:
    def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
        return httpx.Response(200, json={"unexpected": "shape"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with httpx.Client() as client, pytest.raises(YandexGPTError):
        classify_topic(client, SETTINGS, "текст")


def test_classify_topic_truncates_long_transcript(monkeypatch) -> None:
    captured = {}

    def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
        captured["user_text"] = json["messages"][1]["text"]
        return _completion_response("Не определено")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    long_transcript = "а" * 10_000
    with httpx.Client() as client:
        classify_topic(client, SETTINGS, long_transcript)

    assert len(captured["user_text"]) == 6000
