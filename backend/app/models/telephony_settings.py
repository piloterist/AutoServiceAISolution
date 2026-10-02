"""IP-телефония connection/schedule settings, editable from Settings ->
IP-телефония, not just env vars - see app/models/app_settings.py for the
same single-row-per-instance pattern this follows (single-tenant hosted:
one instance per client, so there is only ever one row, fixed at id=1).

First (and so far only) provider is Zeon - `provider` exists so a future
second provider can be added without a schema rename, but nothing branches
on it yet (see services/zeon_client.py).

Values live here, not in app/core/config.py, specifically so an operator
can wire up/rotate the Zeon API key or the poll schedule without a
redeploy - the same reasoning as AppSettings.fivesystems_api_enabled vs
core/config.py's ENABLE_FIVESYSTEMS_LOOKUP.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PROVIDER_ZEON = "zeon"

# Mirrors Zeon_AI's ZEON_AUTH: bearer (https only) or hash (md5 signature -
# see services/zeon_client.py).
ZEON_AUTH_BEARER = "bearer"
ZEON_AUTH_HASH = "hash"
ZEON_AUTH_MODES = (ZEON_AUTH_BEARER, ZEON_AUTH_HASH)

# Mirrors Zeon_AI's ZEON_AUDIO_METHOD - see services/zeon_client.py's
# download_audio().
ZEON_AUDIO_METHOD_MP3 = "get-mp3"
ZEON_AUDIO_METHOD_FILE = "get-file"
ZEON_AUDIO_METHODS = (ZEON_AUDIO_METHOD_MP3, ZEON_AUDIO_METHOD_FILE)


class TelephonySettings(Base):
    __tablename__ = "telephony_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    provider: Mapped[str] = mapped_column(String(20), nullable=False, default=PROVIDER_ZEON)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    zeon_api_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    zeon_api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    zeon_auth: Mapped[str] = mapped_column(String(10), nullable=False, default=ZEON_AUTH_BEARER)

    # Archival copy of each computed snapshot, same folder shape the
    # standalone Zeon_AI script already writes to (disk:/ZEON/<day>/...) -
    # kept for other existing consumers of that Disk folder (e.g. the
    # manual weekly QA report), not for our own ingestion, which reads
    # straight from telephony_calls instead. Optional: blank token disables
    # archival without disabling the import itself.
    yandex_disk_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    yandex_disk_base_path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # "302:Алексей,303:Мария" - same format as Zeon_AI's OPERATOR_NAMES env
    # var, parsed by services/zeon_client.py. Free text so it can be edited
    # without a schema change; not worth its own table for a handful of
    # extensions.
    operator_names: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # How often the background import loop re-fetches calls, in minutes -
    # see services/telephony_relay.py. Null/0 = scheduled import is off; the
    # manual "Импортировать" button (see endpoints/telephony.py) still
    # works regardless, since it is deliberately not tied to this schedule.
    poll_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Call recording export + Yandex SpeechKit transcription (see
    # services/call_recording_service.py) - a separate, button-triggered
    # pipeline, deliberately not tied to the poll_interval_minutes schedule
    # above (see that module's docstring for why). Recordings/transcripts
    # are archived to the same yandex_disk_token/yandex_disk_base_path
    # already used for the stats snapshot archive.
    zeon_audio_method: Mapped[str] = mapped_column(
        String(10), nullable=False, default=ZEON_AUDIO_METHOD_MP3
    )
    # Yandex Cloud service-account API key with the ai.speechkit-stt.user
    # role - see https://cloud.yandex.ru/docs/speechkit/concepts/auth.
    yc_api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    yc_folder_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    speechkit_model: Mapped[str] = mapped_column(String(30), nullable=False, default="general")
    speechkit_language: Mapped[str] = mapped_column(String(10), nullable=False, default="ru-RU")
    # How long a single export-and-transcribe run waits for SpeechKit
    # operations still in flight before giving up on the rest of that
    # batch (see call_recording_service.transcribe_recordings) - the batch
    # is safe to just run again later, already-finished files are skipped.
    speechkit_timeout_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)

    # --- Call topic classification via YandexGPT (see
    # services/yandexgpt_client.py, services/call_transcription_relay.py) -
    # a separate automatic pipeline from the SpeechKit settings above, off
    # by default (an extra paid call per transcript). Reuses yc_api_key/
    # yc_folder_id - Yandex Foundation Models accepts the same Api-Key auth
    # SpeechKit does, just needs the ai.languageModels.user role added to
    # that same service account.
    classify_calls_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Suffix after "gpt://<folder_id>/" - e.g. "yandexgpt-lite/latest"
    # (cheaper, used by default) vs "yandexgpt/latest" (full model).
    yandexgpt_model: Mapped[str] = mapped_column(
        String(50), nullable=False, default="yandexgpt-lite/latest"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<TelephonySettings provider={self.provider!r} enabled={self.enabled}>"
