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
    "Нецелевой звонок — ЛЮБОЙ звонок, где звонящий не является клиентом, "
    "обращающимся по вопросу ремонта/обслуживания/покупки услуг "
    "автосервиса, независимо от конкретной причины. Это не только "
    "очевидный спам или ошибка номером — так же считаются, например: "
    "звонок от стороннего бизнеса, предлагающего ЧТО-ТО самому "
    "автосервису (подбор персонала/рекрутинг, реклама, маркетинг, "
    "продажа ПО/оборудования, работа с площадками типа Авито/Авто.ру), "
    "звонок поставщика запчастей/оборудования, звонок своих сотрудников, "
    "звонок по уже оформленному заказу без вопроса о записи. Такие "
    "звонки НЕ оценивай по чек-листу ниже (чек-лист — про обслуживание "
    "клиента автосервиса, здесь оценивать просто нечего) — оцени мягче, "
    "по общей вежливости и адекватности общения, и явно напиши в review, "
    "что звонок нецелевой и почему (кто звонил и с какой целью). "
    "КОНКРЕТНО ПО БАЛЛУ: нецелевой звонок — это НЕ «Проблемный» и НЕ "
    "«Лид потерян» (к нему не может быть применён чек-лист про запись "
    "клиента, значит не может быть и его провала), даже если сотрудник "
    "ничего не выяснил и никого никуда не записал — там и выяснять/"
    "записывать было нечего. Если сотрудник был вежлив и адекватен — "
    "ставь 7-10 вне зависимости от того, что по чек-листу было бы низко; "
    "ставь ниже 7 (вплоть до 1-3) ТОЛЬКО если сотрудник был груб, "
    "раздражён или некорректен с самим звонящим — а не за то, что не "
    "продал ему автоуслугу, которую тот и не спрашивал.\n"
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
    "записал клиента; если записать сразу нельзя (например, нет свободных "
    "слотов) — договорился о следующем шаге с конкретным сроком, который "
    "ИНИЦИИРУЕТ сам сотрудник (точное время, когда он перезвонит с "
    "ответом, или когда освободится место), с записанными контактами "
    "клиента. Фраза вида «наберите нас, если что»/«ждём вашего звонка» "
    "этому условию НЕ удовлетворяет — сотрудник переложил ответственность "
    "на клиента вместо того чтобы взять её на себя, это равносильно "
    "отсутствию следующего шага. ВАЖНО: если машина клиента УЖЕ находится в "
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
    "запись не сделана — ОТСУТСТВИЕ СВОБОДНЫХ МЕСТ/СЛОТОВ САМО ПО СЕБЕ НЕ "
    "ОПРАВДЫВАЕТ этот пункт и не смягчает оценку: если записать прямо "
    "сейчас физически нельзя, это разрешается только зафиксированным "
    "сотрудником конкретным следующим шагом — точная дата/время, когда "
    "появится место, ИЛИ точное время, когда сотрудник САМ перезвонит с "
    "ответом, да ещё и с записанными контактами клиента; пообещал "
    "перезвонить без срока и без записи имени и телефона клиента; "
    "переложил обязанность связаться обратно на клиента («наберите, если "
    "что», «ждём вашего звонка», «перезвоните, если решите») вместо того "
    "чтобы самому зафиксировать срок и взять инициативу перезвонить — по "
    "факту это так же означает отсутствие следующего шага, даже если до "
    "этого сотрудник честно пытался подобрать вариант; негатив о "
    "компании/коллегах/руководстве; явно ложная или некорректная "
    "информация.\n"
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
# Long calls are not sent whole: product ask, 2026-11-06 - a 707 s call (11 333 characters of raw
# text) came back from the rewrite as 1 573 characters, whole paragraphs gone, because a model
# asked to "clean up" a big text summarises it. Each piece below is small enough that the model
# has nothing to condense, and the answer is checked against the piece it came from.
ADAPT_CHUNK_CHARS = 2500
# Hard cap on what is sent at all (cost/latency for a pathological call); the rest stays raw.
MAX_ADAPT_TRANSCRIPT_CHARS = 60000
# A piece whose answer is shorter than this share of the input is treated as a summary, not a
# clean-up (noise and filler legitimately shrink a piece, but not by half).
MIN_KEPT_RATIO = 0.6
# Below this the ratio is meaningless (a couple of lines).
MIN_CHECKED_CHUNK_CHARS = 400

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


# Both _ADAPT_SYSTEM_PROMPT and _REWRITE_SYSTEM_PROMPT explicitly require
# this exact output format back ("каждая реплика на отдельной строке
# «Говорящий N: текст»") - a real adapted/rewritten transcript always has
# at least one such line.
_SPEAKER_LINE_RE = re.compile(r"Говорящий\s*\d+\s*:")


def _looks_like_transcript(text: str) -> bool:
    """Guards against a model refusal or other off-task answer standing in
    for the real transcript (confirmed live, 2026-10-21: YandexGPT answered
    "Я не могу обсуждать эту тему. Давайте поговорим о чём-нибудь ещё." for
    an entirely unremarkable repair-estimate call, no sensitive content at
    all - just an occasional false-positive refusal). That text is
    non-empty, so the old `adapted or transcript_text` check let it straight
    through as if it were the real transcript - and the quality-assessment
    step then reviewed the refusal text itself, producing a nonsensical
    review quoting a sentence the operator never said."""
    return bool(_SPEAKER_LINE_RE.search(text))


def _split_transcript(text: str, limit: int = ADAPT_CHUNK_CHARS) -> list[str]:
    """Splits on speaker-line boundaries into pieces of at most ~limit characters (one very long
    line stays a piece of its own) - the model gets a manageable fragment, never a cut-off line."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines():
        if current and size + len(line) + 1 > limit:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _complete_transcript(
    client: httpx.Client, settings: YandexGPTSettings, system_prompt: str, chunk: str
) -> str | None:
    """One piece through the model; None on any failure or an answer that is not a transcript."""
    body = {
        "modelUri": _model_uri(settings),
        "completionOptions": {
            "stream": False,
            "temperature": TEMPERATURE,
            "maxTokens": MAX_ADAPT_COMPLETION_TOKENS,
        },
        "messages": [
            {"role": "system", "text": system_prompt},
            {"role": "user", "text": chunk},
        ],
    }
    try:
        response = client.post(COMPLETION_URL, json=body, headers=_headers(settings))
        if response.status_code != 200:
            raise _error(response, "completion")
        alternatives = response.json()["result"]["alternatives"]
        raw_answer = alternatives[0]["message"]["text"]
    except (httpx.HTTPError, YandexGPTError, KeyError, IndexError, ValueError):
        return None
    answer = raw_answer.strip()
    if not answer or not _looks_like_transcript(answer):
        return None
    return answer


def _is_summary(source: str, answer: str) -> bool:
    return len(source) >= MIN_CHECKED_CHUNK_CHARS and len(answer) < MIN_KEPT_RATIO * len(source)


def _process_transcript(
    client: httpx.Client,
    settings: YandexGPTSettings,
    transcript_text: str,
    prompts: tuple[str, ...],
) -> str:
    """Runs the transcript through the model piece by piece. For every piece the prompts are tried
    in order and the first answer that is a transcript and not a summary (see _is_summary) wins;
    when none qualifies, the piece stays as SpeechKit wrote it - a messy but complete text beats a
    tidy one with paragraphs missing. Never raises."""
    transcript = transcript_text.strip()
    if not transcript:
        return transcript_text
    head, tail = transcript[:MAX_ADAPT_TRANSCRIPT_CHARS], transcript[MAX_ADAPT_TRANSCRIPT_CHARS:]

    parts: list[str] = []
    for chunk in _split_transcript(head):
        chosen = chunk
        for prompt in prompts:
            answer = _complete_transcript(client, settings, prompt, chunk)
            if answer is not None and not _is_summary(chunk, answer):
                chosen = answer
                break
        parts.append(chosen)
    if tail:
        parts.append(tail.strip())
    return "\n".join(parts)


def adapt_transcript(
    client: httpx.Client, settings: YandexGPTSettings, transcript_text: str
) -> str:
    """Lightly corrects a raw SpeechKit transcript (recognition artifacts, mis-split speaker turns)
    before it's used for topic summary/quality assessment - see module comment above. Works piece
    by piece and falls back to the original text of a piece on any failure or a too-short answer
    (see _process_transcript) - adaptation is a quality improvement, never a reason to lose the
    call's transcript (see call_transcription_service.py's caller)."""
    return _process_transcript(client, settings, transcript_text, (_ADAPT_SYSTEM_PROMPT,))


# --- Transcript rewrite (product ask, 2026-10-07: even after adapt_
# transcript's light touch-up, "половина фраз - с ошибками или определена
# не тому говорящему... почти нереально читать" - a new opt-in, separate
# from adaptation above, see TelephonySettings.transcript_rewrite_enabled)
# - this one paraphrases freely to produce a clean, readable dialogue,
# trading closeness to the exact original wording for actually being
# legible. Mutually exclusive with adapt_transcript at the call site (see
# call_transcription_service.py._transcribe) - never both on the same
# call, since rewriting an already-adapted transcript buys nothing.

_REWRITE_SYSTEM_PROMPT = (
    "Тебе присылают автоматическую расшифровку (Yandex SpeechKit) ФРАГМЕНТА "
    "телефонного разговора сотрудника автосервиса с клиентом. Распознавание "
    "речи и определение говорящих в ней работают плохо: много слов "
    "распознано с ошибками, реплики часто разорваны на части и перепутаны "
    "между говорящими, из-за чего разговор трудно читать.\n"
    "\n"
    "Твоя задача — привести расшифровку в читаемый вид, НЕ СОКРАЩАЯ "
    "разговор. Это правка, а не пересказ и не резюме.\n"
    "\n"
    "ГЛАВНОЕ ПРАВИЛО — ПОЛНОТА. Каждая содержательная мысль, вопрос, "
    "ответ, цифра, дата, сумма, срок, название детали, марка и модель "
    "машины, возражение и договорённость из исходного текста должны "
    "остаться в результате. Если в исходном фрагменте клиент или "
    "сотрудник говорят на какую-то тему несколько реплик подряд — все эти "
    "реплики должны быть в ответе, а не одно обобщающее предложение. "
    "Результат должен быть примерно той же длины, что и исходный текст: "
    "короче можно стать только за счёт слов-паразитов, пауз и мусора "
    "распознавания (см. ниже), и обычно это не больше 15–25% объёма. "
    "Результат короче половины исходного текста — это ошибка.\n"
    "\n"
    "ОСОБОЕ ВНИМАНИЕ — МАРКЕ И МОДЕЛИ АВТОМОБИЛЯ. SpeechKit особенно часто "
    "искажает именно её (редкое для русской речи сочетание звуков). "
    "Внимательно ищи любое упоминание марки или модели — даже обрывочное, "
    "странно разбитое на слова или фонетически искажённое (например, «ладо "
    "ларгус», «лада ларгус» — это «Lada Largus»; «хёндай солярис», «хундай "
    "солярис» — «Hyundai Solaris»; «раф 4» — «Toyota RAV4»). Если по "
    "звучанию и контексту понятно, что речь о конкретной машине — впиши "
    "правильное общепринятое название вместо искажённого. Если марка или "
    "модель нигде не звучит — не придумывай её.\n"
    "\n"
    "Как определять, кто есть кто: сотрудник автосервиса представляется "
    "от лица компании и говорит о машине клиента как о чужой («ваша "
    "машина», «мы передадим на сборку»); клиент звонит по поводу своей "
    "машины и говорит о ней от первого лица.\n"
    "\n"
    "Можно:\n"
    "— Исправлять явные ошибки распознавания слов, когда из контекста "
    "ясно, что имелось в виду.\n"
    "— Переставлять реплики между говорящими и объединять разорванные куски "
    "одной мысли, опираясь на смысл, а не на разметку SpeechKit.\n"
    "— Слегка править формулировки для связности, сохраняя содержание "
    "каждой реплики и манеру речи говорящего.\n"
    "— Убирать слова-паразиты («ну», «вот», «значит», «э-э»), одиночные "
    "«алло» при плохой связи, обрывки без смысла и подряд идущие дубли "
    "одного и того же слова.\n"
    "\n"
    "Нельзя:\n"
    "— Пропускать и склеивать в одну фразу целые куски разговора, "
    "пересказывать их или подводить итог.\n"
    "— Убирать реплики только потому, что они кажутся незначительными, "
    "бытовыми или повторяют сказанное ранее по смыслу: если человек "
    "возвращается к вопросу, это тоже часть разговора.\n"
    "— Добавлять факты, приветствия, прощания и любые реплики, которых не "
    "было в тексте, и менять суть договорённостей (сроки, цены, что "
    "именно обещали сделать).\n"
    "\n"
    "Формат вывода — такой же, как на входе: каждая реплика на отдельной "
    "строке «Говорящий N: текст», в хронологическом порядке, та же "
    "нумерация говорящих. Ответь СТРОГО только исправленным текстом "
    "фрагмента, без пояснений, без markdown, без текста до или после."
)


def rewrite_transcript(
    client: httpx.Client, settings: YandexGPTSettings, transcript_text: str
) -> str:
    """Rewrites a raw SpeechKit transcript into a clean, readable dialogue - see
    TelephonySettings.transcript_rewrite_enabled and the module comment above for how this differs
    from adapt_transcript's light touch-up. Same fallback contract as adapt_transcript; a piece the
    rewrite answered with a summary (see _is_summary) is retried with the stricter adaptation
    prompt, and kept raw if that comes back short too."""
    return _process_transcript(
        client, settings, transcript_text, (_REWRITE_SYSTEM_PROMPT, _ADAPT_SYSTEM_PROMPT)
    )


def new_client() -> httpx.Client:
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
