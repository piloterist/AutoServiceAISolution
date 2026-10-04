"""Read/write access to the single telephony_settings row and the
phone_sources directory - see models/telephony_settings.py and
models/phone_source.py. Same singleton pattern as services/settings_service.py.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.phone_source import PhoneSource
from app.models.telephony_settings import ZEON_AUTH_BEARER, TelephonySettings
from app.models.workshop_phone_mapping import WorkshopPhoneMapping
from app.services.call_workshop_service import normalize_phone_or_line

SETTINGS_ID = 1


def get_telephony_settings(db: Session) -> TelephonySettings:
    settings = db.get(TelephonySettings, SETTINGS_ID)
    if settings is None:
        settings = TelephonySettings(id=SETTINGS_ID, zeon_auth=ZEON_AUTH_BEARER)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_telephony_settings(
    db: Session,
    *,
    enabled: bool,
    zeon_api_url: str | None,
    zeon_api_key: str | None,
    zeon_auth: str,
    yandex_disk_token: str | None,
    yandex_disk_base_path: str | None,
    operator_names: str | None,
    poll_interval_minutes: int | None,
    zeon_audio_method: str,
    yc_api_key: str | None,
    yc_folder_id: str | None,
    speechkit_model: str,
    speechkit_language: str,
    speechkit_timeout_min: int,
    classify_calls_enabled: bool,
    yandexgpt_model: str,
    assess_quality_enabled: bool,
    transcription_poll_interval_minutes: int,
    transcription_batch_size: int,
) -> TelephonySettings:
    settings = get_telephony_settings(db)
    settings.enabled = enabled
    settings.zeon_api_url = zeon_api_url
    settings.zeon_api_key = zeon_api_key
    settings.zeon_auth = zeon_auth
    settings.yandex_disk_token = yandex_disk_token
    settings.yandex_disk_base_path = yandex_disk_base_path
    settings.operator_names = operator_names
    settings.poll_interval_minutes = poll_interval_minutes
    settings.zeon_audio_method = zeon_audio_method
    settings.yc_api_key = yc_api_key
    settings.yc_folder_id = yc_folder_id
    settings.speechkit_model = speechkit_model
    settings.speechkit_language = speechkit_language
    settings.speechkit_timeout_min = speechkit_timeout_min
    settings.classify_calls_enabled = classify_calls_enabled
    settings.yandexgpt_model = yandexgpt_model
    settings.assess_quality_enabled = assess_quality_enabled
    settings.transcription_poll_interval_minutes = transcription_poll_interval_minutes
    settings.transcription_batch_size = transcription_batch_size
    db.commit()
    db.refresh(settings)
    return settings


# ---- Источники (phone_sources) ------------------------------------------


def list_phone_sources(db: Session) -> list[PhoneSource]:
    return list(
        db.scalars(select(PhoneSource).order_by(PhoneSource.group_name, PhoneSource.sort_order))
    )


def create_phone_source(
    db: Session, *, line_code: str, name: str, caption: str | None, group_name: str, sort_order: int
) -> PhoneSource:
    source = PhoneSource(
        line_code=line_code.strip(),
        name=name.strip(),
        caption=caption.strip() if caption else None,
        group_name=group_name,
        sort_order=sort_order,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def update_phone_source(
    db: Session,
    source_id: uuid.UUID,
    *,
    line_code: str,
    name: str,
    caption: str | None,
    group_name: str,
    sort_order: int,
) -> PhoneSource | None:
    source = db.get(PhoneSource, source_id)
    if source is None:
        return None
    source.line_code = line_code.strip()
    source.name = name.strip()
    source.caption = caption.strip() if caption else None
    source.group_name = group_name
    source.sort_order = sort_order
    db.commit()
    db.refresh(source)
    return source


def delete_phone_source(db: Session, source_id: uuid.UUID) -> bool:
    source = db.get(PhoneSource, source_id)
    if source is None:
        return False
    db.delete(source)
    db.commit()
    return True


# ---- Цех — Телефон — Добавочный (workshop_phone_mappings) -----------------
#
# A separate, narrower table from phone_sources above - see models/
# workshop_phone_mapping.py's own docstring for why they're not the same
# concept. Writes here don't themselves recompute any CallRecord.workshop_id
# - see endpoints/telephony.py's own explicit "Пересчитать цеха" action,
# which calls call_workshop_service.recompute_all after any add/edit/delete.


def list_workshop_phone_mappings(db: Session) -> list[WorkshopPhoneMapping]:
    return list(db.scalars(select(WorkshopPhoneMapping).order_by(WorkshopPhoneMapping.created_at)))


def create_workshop_phone_mapping(
    db: Session, *, workshop_id: uuid.UUID, phone: str | None, extension: str | None
) -> WorkshopPhoneMapping:
    mapping = WorkshopPhoneMapping(
        workshop_id=workshop_id,
        phone=normalize_phone_or_line(phone) if phone else None,
        extension=extension.strip() if extension else None,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


def update_workshop_phone_mapping(
    db: Session,
    mapping_id: uuid.UUID,
    *,
    workshop_id: uuid.UUID,
    phone: str | None,
    extension: str | None,
) -> WorkshopPhoneMapping | None:
    mapping = db.get(WorkshopPhoneMapping, mapping_id)
    if mapping is None:
        return None
    mapping.workshop_id = workshop_id
    mapping.phone = normalize_phone_or_line(phone) if phone else None
    mapping.extension = extension.strip() if extension else None
    db.commit()
    db.refresh(mapping)
    return mapping


def delete_workshop_phone_mapping(db: Session, mapping_id: uuid.UUID) -> bool:
    mapping = db.get(WorkshopPhoneMapping, mapping_id)
    if mapping is None:
        return False
    db.delete(mapping)
    db.commit()
    return True
