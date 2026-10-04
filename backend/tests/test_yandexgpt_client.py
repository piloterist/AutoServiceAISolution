"""Tests for services/yandexgpt_client.py - the call-topic summary client
(Yandex Foundation Models). No real network calls - httpx.Client.post is
monkeypatched per test, same approach as test_speechkit_client.py would use
for the sibling SpeechKit client.
"""

import httpx
import pytest

from app.services.yandexgpt_client import (
    TOPIC_UNDETERMINED,
    YandexGPTError,
    YandexGPTSettings,
    assess_call_quality,
    summarize_call_topic,
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


def test_summarize_call_topic_sends_expected_request_shape(monkeypatch) -> None:
    captured = {}

    def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _completion_response("Покраска бампера после удара")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    with httpx.Client() as client:
        result = summarize_call_topic(
            client, SETTINGS, "Клиент: нужна покраска бампера после удара"
        )

    assert result == "Покраска бампера после удара"
    assert captured["url"] == "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    assert captured["headers"]["Authorization"] == "Api-Key test-key"
    assert captured["headers"]["x-folder-id"] == "folder-1"
    assert captured["json"]["modelUri"] == "gpt://folder-1/yandexgpt-lite/latest"
    assert captured["json"]["messages"][1]["text"].startswith("Клиент: нужна покраска")


@pytest.mark.parametrize(
    ("raw_answer", "expected"),
    [
        ("Стоимость замены колодок на Chery Tiggo 8", "Стоимость замены колодок на Chery Tiggo 8"),
        ('"Запись на ремонт вмятины"', "Запись на ремонт вмятины"),
        ("«Дефектовка после ДТП Ауди Q7».", "Дефектовка после ДТП Ауди Q7"),
        ("Тема не определена", TOPIC_UNDETERMINED),
        ("   ", TOPIC_UNDETERMINED),
        ("", TOPIC_UNDETERMINED),
    ],
)
def test_summarize_call_topic_parses_model_answer(monkeypatch, raw_answer, expected) -> None:
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, json=None, headers=None: _completion_response(raw_answer),
    )
    with httpx.Client() as client:
        assert summarize_call_topic(client, SETTINGS, "любой текст") == expected


def test_summarize_call_topic_truncates_an_overly_long_answer(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, json=None, headers=None: _completion_response("а" * 500),
    )
    with httpx.Client() as client:
        result = summarize_call_topic(client, SETTINGS, "текст")
    assert len(result) == 200


def test_summarize_call_topic_empty_transcript_returns_undetermined_without_request(
    monkeypatch,
) -> None:
    def fail_post(self, *a, **kw):  # noqa: ANN001
        raise AssertionError("should not call the API for an empty transcript")

    monkeypatch.setattr(httpx.Client, "post", fail_post)
    with httpx.Client() as client:
        assert summarize_call_topic(client, SETTINGS, "   ") == TOPIC_UNDETERMINED


def test_summarize_call_topic_raises_on_http_error(monkeypatch) -> None:
    def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
        return httpx.Response(
            401, json={"message": "Unauthorized"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with httpx.Client() as client, pytest.raises(YandexGPTError):
        summarize_call_topic(client, SETTINGS, "текст")


def test_summarize_call_topic_raises_on_unexpected_response_shape(monkeypatch) -> None:
    def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
        return httpx.Response(200, json={"unexpected": "shape"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with httpx.Client() as client, pytest.raises(YandexGPTError):
        summarize_call_topic(client, SETTINGS, "текст")


def test_summarize_call_topic_truncates_long_transcript(monkeypatch) -> None:
    captured = {}

    def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
        captured["user_text"] = json["messages"][1]["text"]
        return _completion_response("Не определено")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    long_transcript = "а" * 10_000
    with httpx.Client() as client:
        summarize_call_topic(client, SETTINGS, long_transcript)

    assert len(captured["user_text"]) == 6000


# ---- assess_call_quality / QA review -----------------------------------


def test_assess_call_quality_parses_score_and_review(monkeypatch) -> None:
    def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
        return _completion_response(
            '{"score": 8, "review": "Записал клиента на завтра, 10:00. Не взял номер телефона."}'
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with httpx.Client() as client:
        result = assess_call_quality(client, SETTINGS, "Клиент: когда можно записаться?")

    assert result.score == 8
    assert "завтра" in result.review


@pytest.mark.parametrize(
    ("raw_answer", "expected_score"),
    [
        # Markdown fence around the JSON - tolerated.
        ('```json\n{"score": 5, "review": "Средне."}\n```', 5),
        # Stray text around the object.
        ('Вот оценка: {"score": 3, "review": "Отказал без альтернативы."} Спасибо.', 3),
        # Float score - coerced to int.
        ('{"score": 7.0, "review": "Норм."}', 7),
        # Out-of-range score - clamped into 1..10.
        ('{"score": 15, "review": "Отлично."}', 10),
        ('{"score": 0, "review": "Плохо."}', 1),
    ],
)
def test_assess_call_quality_tolerates_formatting_drift(
    monkeypatch, raw_answer, expected_score
) -> None:
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, json=None, headers=None: _completion_response(raw_answer),
    )
    with httpx.Client() as client:
        result = assess_call_quality(client, SETTINGS, "текст")

    assert result.score == expected_score


def test_assess_call_quality_raises_on_unparsable_answer(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, json=None, headers=None: _completion_response("не могу оценить"),
    )
    with httpx.Client() as client, pytest.raises(YandexGPTError):
        assess_call_quality(client, SETTINGS, "текст")


def test_assess_call_quality_raises_on_missing_review_field(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, json=None, headers=None: _completion_response('{"score": 5}'),
    )
    with httpx.Client() as client, pytest.raises(YandexGPTError):
        assess_call_quality(client, SETTINGS, "текст")


def test_assess_call_quality_raises_on_empty_transcript(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not call the API")),
    )
    with httpx.Client() as client, pytest.raises(YandexGPTError):
        assess_call_quality(client, SETTINGS, "   ")


def test_assess_call_quality_raises_on_http_error(monkeypatch) -> None:
    def fake_post(self, url, json=None, headers=None):  # noqa: ANN001
        return httpx.Response(500, json={"message": "internal"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with httpx.Client() as client, pytest.raises(YandexGPTError):
        assess_call_quality(client, SETTINGS, "текст")
