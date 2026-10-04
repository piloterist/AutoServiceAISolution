"""Yandex Foundation Models (YandexGPT) client - writes a short free-text
summary of a finished call transcript (what the call was actually about),
and separately produces a QA review + 1-10 score for
services/call_transcription_service.py.

Same shape as services/speechkit_client.py (a plain `httpx.Client` passed
in, same `Api-Key` auth), deliberately not sharing code with it - the
Foundation Models completion API is a single synchronous request/response
(no submit -> poll -> fetch-result dance like SpeechKit's async
recognition), so there is nothing in common to factor out beyond the auth
header shape.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
REQUEST_TIMEOUT_SECONDS = 30.0

# A short headline, not a classification word - needs more than 16 tokens.
MAX_COMPLETION_TOKENS = "64"
TEMPERATURE = 0.0

# Transcripts run long for a genuinely rambling call; truncated rather than
# sent whole - this is a one-line-summary prompt, not a full analysis, and a
# cap keeps cost/latency predictable regardless of call length. Cheap enough
# (and conversations front-load what they're about) that the first N
# characters are almost always enough to tell what the call was about.
MAX_TRANSCRIPT_CHARS = 6000

# Stored as-is in CallRecord.topic_tag (see models/call_record.py) - a
# hard cap mostly to keep a misbehaving model answer from writing an
# essay into that column, not a limit expected to bite in practice.
MAX_TOPIC_SUMMARY_CHARS = 200

TOPIC_UNDETERMINED = "Тема не определена"

_SYSTEM_PROMPT = (
    "Ты — ассистент автосервиса. Тебе присылают расшифровку телефонного "
    "разговора с клиентом. Напиши ОЧЕНЬ короткое резюме на русском языке "
    "(3-8 слов): с чем конкретно обратился клиент, и по какой машине "
    "(марка/модель), если она прозвучала в разговоре. Пиши по сути, как "
    "заголовок, без вводных слов и кавычек.\n"
    "Примеры хорошего ответа: «Стоимость замены колодок на Chery Tiggo 8», "
    "«Запись на ремонт вмятины», «Дефектовка после ДТП Ауди Q7».\n"
    "Если из разговора невозможно понять суть обращения (звонок не про "
    "автосервис, ошиблись номером, реклама, разговор слишком "
    "короткий/непонятный) — ответь ровно «Тема не определена».\n"
    "Ответь СТРОГО одной короткой фразой без пояснений и без точки в конце."
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


def _parse_topic_summary(raw_text: str) -> str:
    """Cleans up the model's free-text answer - strips surrounding quotes
    (the model sometimes wraps its own answer in «» or "" despite being
    asked not to) and a trailing period, in any order (a single strip() call
    with a combined character set peels them off both ends together,
    regardless of which comes first/last - e.g. '«...».' -> '...'), and
    enforces the storage cap. Never raises and never returns an empty
    string - an empty/whitespace-only answer falls back to
    TOPIC_UNDETERMINED, same as the model explicitly saying it couldn't
    tell."""
    text = raw_text.strip(" \t\r\n\"'«».")
    if not text:
        return TOPIC_UNDETERMINED
    return text[:MAX_TOPIC_SUMMARY_CHARS]


# --- QA review + 1-10 score (product ask, 2026-10-04: "профессиональный но
# краткий разбор и ставить рейтинг", adapted from the operator's own
# daily-batch QA prompt - see the product brief - down to a single-call,
# 1-10-scale version: that prompt's 100-point checklist/category bands are
# folded into the system prompt below as guidance for the model, not
# computed here, since this only ever sees one call's transcript, not the
# whole day's cross-call context (missed-call follow-ups, per-operator
# patterns) that prompt's full report also used.

MAX_QUALITY_COMPLETION_TOKENS = "500"
MAX_QUALITY_TRANSCRIPT_CHARS = 12000
MIN_QUALITY_SCORE = 1
MAX_QUALITY_SCORE = 10

_QUALITY_SYSTEM_PROMPT = (
    "Ты — старший специалист отдела контроля качества (QA) автосервиса. Тебе "
    "присылают расшифровку одного телефонного разговора сотрудника с клиентом "
    "(входящий или исходящий). Оцени работу сотрудника строго, объективно и "
    "по фактам, опираясь только на текст расшифровки - ничего не додумывай, "
    "каждую претензию подтверждай сутью или короткой цитатой из текста. "
    "Главный критерий - довёл ли сотрудник обращение до записи/визита или "
    "сделал всё возможное, чтобы не потерять клиента.\n\n"
    "Расшифровка сделана автоматически, может путать, кто говорит, и "
    "содержать ошибки распознавания - не штрафуй за явные ошибки "
    "распознавания, по смыслу разговора сам определи, где клиент, а где "
    "сотрудник. Если звонок не про продажу/запись на обслуживание (например, "
    "по уже оформленному заказу, от поставщика/партнёра, ошиблись номером, "
    "реклама, внутренний разговор сотрудников) - оценивай мягче, по общему "
    "качеству и вежливости общения, не требуя закрытия на запись.\n\n"
    "Ориентируйся на критерии (не обязательно перечислять их в ответе): "
    "приветствие и доброжелательный тон; выявление потребности (марка/модель "
    "автомобиля, суть обращения, уточняющие вопросы); экспертность "
    "консультации; работа с ценой (ориентир «от-до» или объяснение, из чего "
    "складывается цена, а не голая цифра без контекста); работа с "
    "возражениями («дорого», «подумаю», «далеко» - отработал, а не "
    "согласился и отпустил); закрытие на конкретные дату и время записи - "
    "САМЫЙ ВАЖНЫЙ пункт; сбор имени и контакта клиента; резюме и вежливое "
    "завершение разговора.\n\n"
    "Критические ошибки - оценка не выше 3: грубость, раздражение или спор с "
    "клиентом; отказ без альтернативы («не занимаемся», «всё занято» - без "
    "другой даты, услуги или перезвона); клиент явно хотел записаться, а "
    "запись не сделана; пообещал перезвонить без срока и не взял контакт "
    "клиента; отправил к конкурентам; явно ложная или некорректная "
    "информация.\n\n"
    "Поставь ЦЕЛОЕ число от 1 до 10:\n"
    "9-10 - запись сделана или есть чёткий следующий шаг с конкретным сроком, "
    "серьёзных ошибок нет;\n"
    "7-8 - результат есть, но заметны недочёты;\n"
    "4-6 - результат под угрозой, есть существенные ошибки (не выяснил "
    "машину/суть, не предложил запись, назвал цену и отпустил, согласился с "
    "«подумаю» без попытки удержать);\n"
    "1-3 - клиент потерян по вине сотрудника или была критическая ошибка "
    "(см. выше).\n\n"
    "Ответь СТРОГО одним JSON-объектом, без markdown-разметки, без текста "
    "до или после: "
    '{"score": <целое число 1-10>, "review": '
    '"<2-4 предложения по-русски: что было хорошо/плохо по фактам разговора, '
    'коротко что стоило сделать иначе>"}'
)


@dataclass
class QualityAssessment:
    score: int  # 1-10, clamped
    review: str


def _clamp_score(value: int) -> int:
    return max(MIN_QUALITY_SCORE, min(MAX_QUALITY_SCORE, value))


def _parse_quality(raw_text: str) -> QualityAssessment | None:
    """Parses the model's JSON answer - tolerant of a markdown code fence or
    stray text around the object (seen in practice from smaller models
    despite the prompt's own "strictly JSON" instruction), but returns None
    (not a fabricated score) for anything that isn't recoverably JSON - the
    caller treats that as a retryable failure, same as an API/network error,
    never silently stores a made-up rating."""
    text = raw_text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    score = data.get("score")
    review = data.get("review")
    if not isinstance(score, int | float) or not isinstance(review, str) or not review.strip():
        return None
    return QualityAssessment(score=_clamp_score(int(score)), review=review.strip())


def assess_call_quality(
    client: httpx.Client, settings: YandexGPTSettings, transcript_text: str
) -> QualityAssessment:
    """Raises YandexGPTError for anything retryable (request/API failure, or
    an answer that couldn't be parsed as the expected JSON shape) - never
    returns a guessed score. See services/call_transcription_service.py's
    caller for how a failure here is handled (left for the next cycle to
    retry, same as a transcription failure)."""
    transcript = transcript_text.strip()[:MAX_QUALITY_TRANSCRIPT_CHARS]
    if not transcript:
        raise YandexGPTError("empty transcript - nothing to assess")

    body = {
        "modelUri": _model_uri(settings),
        "completionOptions": {
            "stream": False,
            "temperature": TEMPERATURE,
            "maxTokens": MAX_QUALITY_COMPLETION_TOKENS,
        },
        "messages": [
            {"role": "system", "text": _QUALITY_SYSTEM_PROMPT},
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

    assessment = _parse_quality(raw_answer)
    if assessment is None:
        raise YandexGPTError(f"completion: could not parse quality JSON from: {raw_answer[:300]!r}")
    return assessment


def summarize_call_topic(
    client: httpx.Client, settings: YandexGPTSettings, transcript_text: str
) -> str:
    """Writes a short free-text summary of what a finished call transcript
    was about (e.g. "Стоимость замены колодок на Chery Tiggo 8") - always
    returns a non-empty string (TOPIC_UNDETERMINED for an ambiguous/garbled
    model answer), never raises for that case (only for a request/API-level
    failure - see call_transcription_service.py's caller, which treats that
    as "try again next cycle", not "store Тема не определена")."""
    transcript = transcript_text.strip()[:MAX_TRANSCRIPT_CHARS]
    if not transcript:
        return TOPIC_UNDETERMINED

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

    return _parse_topic_summary(raw_answer)


def new_client() -> httpx.Client:
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
