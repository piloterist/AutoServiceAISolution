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
    model: str = "yandexgpt/latest"


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
# краткий разбор и ставить рейтинг"; prompt rewritten 2026-10-05 to the
# operator's own full daily-batch QA methodology - see Example.html/the
# pasted prompt text from that date - adapted down to a single-call,
# 1-10-scale version rather than a whole-day report: the 100-point
# checklist/category bands below are the model's own internal reasoning
# scaffold (not separately computed here, since this only ever sees one
# call's transcript, not the cross-call context - missed-call follow-ups,
# per-operator patterns - that prompt's full report also used), and the
# final 1-10 score is the operator's own 0-100 category bands divided by 10
# (see the explicit mapping in the prompt). Earlier version was miscalibrated
# on exactly the case the operator flagged: scoring down a pure
# status-check call ("машина уже в сервисе, когда будет готова?") for not
# closing on a fresh appointment - there is nothing to book on a call like
# that, and the prompt now says so explicitly in two places (the closing
# criterion itself and the red-flags list), not just the red flags.

MAX_QUALITY_COMPLETION_TOKENS = "700"
MAX_QUALITY_TRANSCRIPT_CHARS = 12000
MIN_QUALITY_SCORE = 1
MAX_QUALITY_SCORE = 10

_QUALITY_SYSTEM_PROMPT = (
    "РОЛЬ\n"
    "Ты — старший специалист отдела контроля качества (QA) автосервиса. 10+ "
    "лет опыта в аудите входящих звонков и обработке лидов в автобизнесе. Ты "
    "оцениваешь работу мастеров-приёмщиков строго, объективно и по фактам. "
    "Главный критерий — довёл ли сотрудник обращение до записи/визита или "
    "сделал всё возможное, чтобы не потерять клиента.\n\n"
    "ПРАВИЛА\n"
    "Опирайся только на текст расшифровки. Ничего не додумывай. Каждую "
    "претензию подтверждай короткой цитатой из текста.\n"
    "Расшифровка сделана автоматически и может содержать ошибки распознавания "
    "речи (включая случаи, где одна фраза одного человека могла быть "
    "ошибочно разбита между «Говорящий 1»/«Говорящий 2»). Не штрафуй за "
    "явные ошибки распознавания; если смысл фразы совсем неясен — не "
    "додумывай её содержание.\n"
    "Нецелевые звонки (спам, поставщики, ошиблись номером, звонок своих "
    "сотрудников, по уже оформленному заказу без вопроса о записи) НЕ "
    "оценивай по чек-листу ниже — оцени мягче, по общей вежливости и "
    "адекватности общения, и явно напиши в review, что звонок нецелевой и "
    "почему.\n"
    "Если из текста не очевидно, кто клиент, а кто сотрудник — определи по "
    "смыслу разговора (кто спрашивает/нуждается в услуге, кто консультирует) "
    "и, если это было неочевидно, упомяни это в review.\n\n"
    "МЕТОДИКА ОЦЕНКИ (внутренний чек-лист на 100 баллов — используй как "
    "основу рассуждения, в ответе баллы по пунктам перечислять не нужно)\n"
    "Приветствие и представление — 5: назвал компанию, своё имя, "
    "доброжелательный тон.\n"
    "Выявление потребности — 20: марка, модель, год/пробег авто; суть "
    "проблемы или вида работ; уточняющие вопросы.\n"
    "Экспертность и консультация — 15: понятно объяснил, что возможно с "
    "машиной и что нужно сделать; не говорил «не знаю» без предложения "
    "узнать и перезвонить.\n"
    "Работа с ценой — 10: назвал ориентир («от … до …») или объяснил, от "
    "чего зависит цена, и предложил диагностику; не называл «голую» цену "
    "без ценности.\n"
    "Работа с возражениями — 10: «дорого», «подумаю», «далеко», «нет "
    "времени» — отработал, а не согласился и отпустил.\n"
    "Закрытие на запись — 25, КЛЮЧЕВОЙ пункт, НО ТОЛЬКО когда клиент "
    "действительно обращается по новой проблеме/услуге, на которую можно "
    "записаться: предложил конкретные дату и время (лучше 2 варианта), "
    "записал клиента; если записать сразу нельзя — договорился о следующем "
    "шаге с конкретным сроком. ВАЖНО: если машина клиента УЖЕ находится в "
    "сервисе/в ремонте и клиент звонит узнать статус, уточнить срок "
    "готовности, что-то обсудить по уже открытому заказ-наряду — "
    "записываться там физически не на что, этот пункт в таком случае НЕ "
    "применяется и не должен снижать оценку.\n"
    "Сбор контактов — 5: узнал имя клиента и подтвердил номер телефона.\n"
    "Резюме и завершение — 5: повторил договорённости, вежливо "
    "попрощался, не бросил трубку первым.\n"
    "Общение — 5: не перебивал, не раздражался, говорил понятно, без "
    "жаргона и грубости.\n\n"
    "КАТЕГОРИИ (итоговая сумма баллов выше)\n"
    "ОТЛИЧНО (85-100): записан или чёткий следующий шаг, серьёзных ошибок "
    "нет.\n"
    "ХОРОШО С ЗАМЕЧАНИЯМИ (65-84): результат есть, но есть недочёты.\n"
    "ПРОБЛЕМНЫЙ (40-64): лид под угрозой, существенные ошибки.\n"
    "ЛИД ПОТЕРЯН / КРИТИЧНО (0-39 ИЛИ любой критический red-flag ниже, "
    "независимо от суммы баллов): клиент ушёл без записи и без следующего "
    "шага по вине сотрудника.\n\n"
    "РЕД-ФЛАГИ\n"
    "Критические (любой из них = категория «Лид потерян/критично», "
    "независимо от суммы баллов): грубость, раздражение, пренебрежительный "
    "тон, спор с клиентом; клиент явно хотел записаться на новую услугу, а "
    "запись не сделана; пообещал перезвонить без срока и без записи имени и "
    "телефона клиента; негатив о компании/коллегах/руководстве; явно ложная "
    "или некорректная информация.\n"
    "Существенные: не выяснил автомобиль или суть проблемы; не предложил "
    "запись/диагностику по новой проблеме (НЕ применяется, если машина уже "
    "в сервисе — см. выше); назвал цену без объяснения и отпустил клиента; "
    "согласился с «я подумаю» без попытки удержать; равнодушие, "
    "односложные ответы, «ну приезжайте как-нибудь»; долгое ожидание на "
    "линии без предупреждения; перебивал клиента, не дослушал.\n"
    "Незначительные: не представился/не назвал компанию; не спросил имя "
    "клиента; не подвёл итог разговора.\n\n"
    "ИТОГОВЫЙ БАЛЛ 1-10 — переведи сумму из 100-балльного чек-листа делением "
    "на 10 и округлением до целого (ОТЛИЧНО -> 9-10, ХОРОШО С ЗАМЕЧАНИЯМИ -> "
    "7-8, ПРОБЛЕМНЫЙ -> 4-6, ЛИД ПОТЕРЯН/КРИТИЧНО -> 1-3, всегда 1-3 при "
    "любом критическом red-flag).\n\n"
    "Ответь СТРОГО одним JSON-объектом, без markdown-разметки, без текста "
    "до или после: "
    '{"score": <целое число 1-10>, "review": '
    '"<3-5 предложений по-русски: сначала короткая категория (Отлично / '
    "Хорошо с замечаниями / Проблемный / Лид потерян), затем что было "
    "хорошо/плохо по фактам разговора с краткими цитатами, что стоило "
    'сделать иначе>"}'
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


# --- Transcript adaptation (product ask, 2026-10-05: "спичкит не очень
# хорошо расшифровывает... адаптировать через YandexGPT чтобы по смыслу
# немного корректировал слова и фразы, правильнее определял говорящего 1 и
# 2") - runs once, right after SpeechKit, before either of the two
# functions above: both read from the adapted text, not the raw one (see
# services/call_transcription_service.py's own _transcribe). The raw
# SpeechKit output is kept too (CallRecord.transcript_text_raw), so this
# step is never a one-way, irreversible edit.

MAX_ADAPT_COMPLETION_TOKENS = "8000"
MAX_ADAPT_TRANSCRIPT_CHARS = 12000

_ADAPT_SYSTEM_PROMPT = (
    "Тебе присылают автоматическую расшифровку (Yandex SpeechKit) одного "
    "телефонного разговора сотрудника автосервиса с клиентом, в формате "
    "построчных реплик «Говорящий N: текст». Диаризация (разбивка по "
    "говорящим) у SpeechKit часто ошибается — путает говорящих местами, "
    "рвёт одну реплику на части между разными «Говорящий N», приклеивает "
    "короткую реакцию одного человека («ага», «угу», «хорошо», «да», "
    "«спасибо», переспрос в одно-два слова вроде «Забрать?», «Сборку?») "
    "в конец/середину чужой длинной реплики. Твоя задача — переразметить "
    "говорящих и порядок реплик ПО СМЫСЛУ разговора, не меняя сам текст "
    "по содержанию.\n"
    "\n"
    "КАК ОПРЕДЕЛЯТЬ, КТО ЕСТЬ КТО (по смыслу, а не по тому, что уже "
    "проставил SpeechKit):\n"
    "— Сотрудник автосервиса: представляется от лица компании и по имени "
    "в начале звонка, говорит о ремонте/машине клиента как о чужой "
    "(«ваша машина», «мы передаём на сборку»), сообщает статус/сроки/"
    "цену, предлагает перезвонить или записать.\n"
    "— Клиент: звонит по поводу СВОЕЙ машины, описывает проблему или "
    "спрашивает статус/цену/сроки своими словами, коротко подтверждает "
    "и благодарит («ага», «хорошо», «спасибо», «угу»).\n"
    "Один и тот же человек должен последовательно оставаться «Говорящий "
    "1» или «Говорящий 2» на протяжении всего разговора — не меняй "
    "нумерацию человека посреди диалога.\n"
    "\n"
    "ЧТО ИСПРАВЛЯТЬ (действуй решительно там, где смысл явно требует "
    "этого, а не только косметически):\n"
    "1. Если целая реплика целиком подписана не на того говорящего "
    "(по смыслу её мог сказать только другой человек) — переставь её "
    "целиком на правильного говорящего.\n"
    "2. Если одна смысловая реплика одного человека ошибочно разбита на "
    "несколько строк между разными «Говорящий N» — объедини их в одну "
    "реплику под верным говорящим, в правильном месте разговора.\n"
    "3. Если короткая реакция/переспрос (одно-два слова вроде «ага», "
    "«угу», «хорошо», «да», «спасибо», «Забрать?», «Сборку?») приклеена "
    "к чужой длинной реплике, хотя по смыслу это ответ ДРУГОГО "
    "участника — вынеси её отдельной строкой под правильным говорящим, "
    "на своё место в хронологии.\n"
    "4. Если из-за ошибки распознавания/наложения речи одно и то же "
    "слово или короткая фраза попали в расшифровку дважды подряд (один "
    "раз как хвост чужой реплики, второй раз отдельной строкой-дублем) "
    "— оставь только одно вхождение, под тем говорящим, кому оно "
    "принадлежит по смыслу, и убери дубль.\n"
    "5. Исправляй также явные, однозначные ошибки распознавания "
    "отдельных слов, когда из контекста понятно, что имелось в виду на "
    "самом деле. Если не уверен — оставляй как есть, не гадай.\n"
    "6. НЕ пересказывай, НЕ сокращай, НЕ суммаризируй, НЕ добавляй ничего "
    "от себя и не убирай ничего по смыслу — только переразметка "
    "говорящих, порядка реплик и лёгкая правка слов.\n"
    "7. Сохраняй точно тот же формат вывода: каждая реплика на отдельной "
    "строке «Говорящий N: текст», в хронологическом порядке разговора.\n"
    "Если расшифровка уже читается нормально и править нечего — верни её "
    "без изменений. Ответь СТРОГО только исправленным текстом расшифровки "
    "целиком, без пояснений, без markdown, без текста до или после."
)


def adapt_transcript(
    client: httpx.Client, settings: YandexGPTSettings, transcript_text: str
) -> str:
    """Lightly corrects a raw SpeechKit transcript (recognition artifacts,
    mis-split speaker turns) before it's used for topic summary/quality
    assessment - see module comment above. Falls back to returning the
    original text unchanged on any failure (an empty transcript, a request/
    API error, or an empty model answer) rather than raising - adaptation
    is a quality improvement, never a reason to lose the call's transcript
    entirely (see call_transcription_service.py's caller)."""
    transcript = transcript_text.strip()[:MAX_ADAPT_TRANSCRIPT_CHARS]
    if not transcript:
        return transcript_text

    body = {
        "modelUri": _model_uri(settings),
        "completionOptions": {
            "stream": False,
            "temperature": TEMPERATURE,
            "maxTokens": MAX_ADAPT_COMPLETION_TOKENS,
        },
        "messages": [
            {"role": "system", "text": _ADAPT_SYSTEM_PROMPT},
            {"role": "user", "text": transcript},
        ],
    }
    try:
        response = client.post(COMPLETION_URL, json=body, headers=_headers(settings))
        if response.status_code != 200:
            raise _error(response, "completion")
        alternatives = response.json()["result"]["alternatives"]
        raw_answer = alternatives[0]["message"]["text"]
    except (httpx.HTTPError, YandexGPTError, KeyError, IndexError, ValueError):
        return transcript_text

    adapted = raw_answer.strip()
    return adapted or transcript_text


def new_client() -> httpx.Client:
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
