"""Yandex Foundation Models (YandexGPT) client - classifies a finished call
transcript as Кузовной/Слесарный/Не определено for
services/call_transcription_service.py.

Same shape as services/speechkit_client.py (a plain `httpx.Client` passed
in, same `Api-Key` auth), deliberately not sharing code with it - the
Foundation Models completion API is a single synchronous request/response
(no submit -> poll -> fetch-result dance like SpeechKit's async
recognition), so there is nothing in common to factor out beyond the auth
header shape.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
REQUEST_TIMEOUT_SECONDS = 30.0

# Keeps the model from rambling - a classification answer is one word.
MAX_COMPLETION_TOKENS = "16"
TEMPERATURE = 0.0

# Transcripts run long for a genuinely rambling call; truncated rather than
# sent whole - this is a classification prompt, not a summary, and a cap
# keeps cost/latency predictable regardless of call length. Cheap enough
# (and conversations front-load what they're about) that the first N
# characters are almost always enough to tell Кузовной from Слесарный.
MAX_TRANSCRIPT_CHARS = 6000

TOPIC_BODY = "Кузовной"
TOPIC_MECHANICAL = "Слесарный"
TOPIC_UNKNOWN = "Не определено"

_SYSTEM_PROMPT = (
    "Ты — ассистент автосервиса. Тебе присылают расшифровку телефонного "
    "разговора с клиентом. Определи, о каком виде ремонта шла речь:\n"
    "— «Кузовной» — покраска, вмятины, ДТП, кузовной ремонт, рихтовка;\n"
    "— «Слесарный» — двигатель, ходовая часть, диагностика, ТО, электрика, "
    "шиномонтаж, любой ремонт не по кузову.\n"
    "Если из разговора непонятно, о чём речь, звонок не про ремонт вообще "
    "(запись на мойку, общий вопрос, жалоба, ошиблись номером, реклама) "
    "или сам разговор слишком короткий/непонятный — ответь «Не определено».\n"
    "Ответь СТРОГО одним словом из списка: Кузовной, Слесарный, Не определено. "
    "Никаких пояснений, знаков препинания или других слов."
)


class YandexGPTError(Exception):
    """Raised on any Foundation Models API failure."""


@dataclass
class YandexGPTSettings:
    api_key: str
    folder_id: str
    model: str = "yandexgpt-lite/latest"


def _headers(settings: YandexGPTSettings) -> dict[str, str]:
    return {
        "Authorization": f"Api-Key {settings.api_key}",
        "x-folder-id": settings.folder_id,
        "Content-Type": "application/json",
    }


def _model_uri(settings: YandexGPTSettings) -> str:
    return f"gpt://{settings.folder_id}/{settings.model}"


def _error(response: httpx.Response, what: str) -> YandexGPTError:
    try:
        info = response.json()
        detail = info.get("message") or info.get("error") or info
    except ValueError:
        detail = response.text[:300]
    return YandexGPTError(f"{what}: HTTP {response.status_code} {detail}")


def _parse_topic(raw_text: str) -> str:
    """Maps the model's free-text answer onto one of the 3 known tags.
    Prefers an exact match (the prompt asks for exactly one word) but falls
    back to a substring check so minor formatting drift (a trailing period,
    extra whitespace, a stray capital) doesn't silently produce a 4th,
    unknown tag value - anything that isn't clearly one of the two shop
    names collapses to "Не определено", never raises."""
    text = raw_text.strip()
    lowered = text.lower()
    if lowered == TOPIC_BODY.lower():
        return TOPIC_BODY
    if lowered == TOPIC_MECHANICAL.lower():
        return TOPIC_MECHANICAL
    if "кузов" in lowered:
        return TOPIC_BODY
    if "слесар" in lowered:
        return TOPIC_MECHANICAL
    return TOPIC_UNKNOWN


def classify_topic(client: httpx.Client, settings: YandexGPTSettings, transcript_text: str) -> str:
    """Classifies a finished call transcript - always returns one of
    TOPIC_BODY/TOPIC_MECHANICAL/TOPIC_UNKNOWN, never raises for an
    ambiguous/garbled model answer (only for a request/API-level failure -
    see call_transcription_service.py's caller, which treats that as "try
    again next cycle", not "this call is Не определено")."""
    transcript = transcript_text.strip()[:MAX_TRANSCRIPT_CHARS]
    if not transcript:
        return TOPIC_UNKNOWN

    body = {
        "modelUri": _model_uri(settings),
        "completionOptions": {
            "stream": False,
            "temperature": TEMPERATURE,
            "maxTokens": MAX_COMPLETION_TOKENS,
        },
        "messages": [
            {"role": "system", "text": _SYSTEM_PROMPT},
            {"role": "user", "text": transcript},
        ],
    }
    try:
        response = client.post(COMPLETION_URL, json=body, headers=_headers(settings))
    except httpx.HTTPError as exc:
        raise YandexGPTError(f"completion request failed: {exc}") from exc
    if response.status_code != 200:
        raise _error(response, "completion")

    try:
        alternatives = response.json()["result"]["alternatives"]
        raw_answer = alternatives[0]["message"]["text"]
    except (KeyError, IndexError, ValueError) as exc:
        raise YandexGPTError(
            f"completion: unexpected response shape: {response.text[:300]}"
        ) from exc

    return _parse_topic(raw_answer)


def new_client() -> httpx.Client:
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
