"""Contract for Settings -> IP-телефония and the call-statistics page."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.models.phone_source import SOURCE_GROUPS
from app.models.telephony_settings import ZEON_AUDIO_METHODS, ZEON_AUTH_MODES

# ---- Настройки подключения ------------------------------------------------


class TelephonySettingsResponse(BaseModel):
    provider: str
    enabled: bool
    zeon_api_url: str | None
    zeon_api_key: str | None
    zeon_auth: str
    yandex_disk_token: str | None
    yandex_disk_base_path: str | None
    operator_names: str | None
    poll_interval_minutes: int | None
    zeon_audio_method: str
    yc_api_key: str | None
    yc_folder_id: str | None
    speechkit_model: str
    speechkit_language: str
    speechkit_timeout_min: int
    classify_calls_enabled: bool
    yandexgpt_model: str

    model_config = {"from_attributes": True}


class TelephonySettingsUpdate(BaseModel):
    enabled: bool = False
    zeon_api_url: str | None = None
    zeon_api_key: str | None = None
    zeon_auth: str = "bearer"
    yandex_disk_token: str | None = None
    yandex_disk_base_path: str | None = None
    operator_names: str | None = None
    poll_interval_minutes: int | None = Field(default=None, gt=0)
    zeon_audio_method: str = "get-mp3"
    yc_api_key: str | None = None
    yc_folder_id: str | None = None
    speechkit_model: str = "general"
    speechkit_language: str = "ru-RU"
    speechkit_timeout_min: int = Field(default=60, gt=0)
    classify_calls_enabled: bool = False
    yandexgpt_model: str = "yandexgpt-lite/latest"

    def validate_choices(self) -> None:
        if self.zeon_auth not in ZEON_AUTH_MODES:
            raise ValueError(f"zeon_auth must be one of {ZEON_AUTH_MODES}")
        if self.zeon_audio_method not in ZEON_AUDIO_METHODS:
            raise ValueError(f"zeon_audio_method must be one of {ZEON_AUDIO_METHODS}")


# ---- Источники (phone_sources) --------------------------------------------


class PhoneSourceOut(BaseModel):
    id: uuid.UUID
    line_code: str
    name: str
    caption: str | None
    group_name: str
    sort_order: int

    model_config = {"from_attributes": True}


class PhoneSourceWrite(BaseModel):
    line_code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    caption: str | None = Field(default=None, max_length=255)
    group_name: str
    sort_order: int = 0

    def validate_choices(self) -> None:
        if self.group_name not in SOURCE_GROUPS:
            raise ValueError(f"group_name must be one of {SOURCE_GROUPS}")


# ---- Проверка соединения / ручной импорт ----------------------------------


class TelephonyPingResult(BaseModel):
    ok: bool
    error: str | None = None


class TelephonyImportRequest(BaseModel):
    # Both optional - omit both for "since the last scheduled import"
    # (services/telephony_import_service.import_recent), or give a range
    # for a manual backfill of specific days.
    start_date: date | None = None
    end_date: date | None = None


class TelephonyImportResponse(BaseModel):
    fetched: int
    upserted: int


# ---- Итог по каждому источнику --------------------------------------------


class SourceSummaryRowOut(BaseModel):
    line_code: str
    name: str
    caption: str | None
    group_name: str
    inbound_total: int
    answered: int
    missed: int
    missed_pct: float | None
    unique_callers: int
    unique_missed_callers: int
    outcome_called_back_reached: int
    outcome_called_back_not_reached: int
    outcome_client_called_back: int
    outcome_no_reaction: int
    reached_pct: float | None

    model_config = {"from_attributes": True}


class SourceSummaryResponse(BaseModel):
    start_date: date
    end_date: date
    rows: list[SourceSummaryRowOut]


# ---- Детализация звонков по источнику (раскрытие строки) ------------------


class LineCallEventOut(BaseModel):
    time: str  # "YYYY-MM-DD HH:MM:SS", Moscow-local
    direction: str  # "in" | "out"
    role: str  # "incoming" | "callback" | "client_recall"
    client: str | None
    operator: str | None
    rang_not_answered: list[str]
    answered: bool
    wait_sec: int
    talk_sec: int
    # YandexGPT's guess at what the call was about - null until
    # transcribed+classified (see services/call_transcription_relay.py), or
    # always null for a call with no real talk time to transcribe.
    topic_tag: str | None
    transcript_text: str | None

    model_config = {"from_attributes": True}


class LineCallsResponse(BaseModel):
    line_code: str
    start_date: date
    end_date: date
    events: list[LineCallEventOut]


# ---- Открытые пропущенные (значок на Планировщике) -------------------------


class OpenMissedCallOut(BaseModel):
    id: str
    client: str
    line: str | None
    source_label: str | None
    direction: str  # "in" | "callback"
    time: str  # "YYYY-MM-DD HH:MM:SS", Moscow-local
    operator: str | None
    rang_not_answered: list[str]

    model_config = {"from_attributes": True}


class OpenMissedCallsResponse(BaseModel):
    count: int
    calls: list[OpenMissedCallOut]


# ---- Выгрузка записей + расшифровка ----------------------------------------


class CallRecordingExportRequest(BaseModel):
    start_date: date
    end_date: date


class CallRecordingExportResponse(BaseModel):
    status: str  # "started" - runs in the background, see endpoints/telephony.py
    start_date: date
    end_date: date
