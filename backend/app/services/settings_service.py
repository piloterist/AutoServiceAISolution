"""Read/write access to the single app_settings row - see models/app_settings.py."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings

SETTINGS_ID = 1


def get_app_settings(db: Session) -> AppSettings:
    """Returns the singleton settings row, creating it with defaults on
    first access - the row doesn't exist until someone opens Settings or
    saves a change, so a fresh deployment isn't missing it.
    """
    settings = db.get(AppSettings, SETTINGS_ID)
    if settings is None:
        settings = AppSettings(id=SETTINGS_ID)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_app_settings(
    db: Session,
    *,
    insurance_repair_type: str | None,
    exclude_internal_insurance: bool,
) -> AppSettings:
    settings = get_app_settings(db)
    settings.insurance_repair_type = insurance_repair_type
    settings.exclude_internal_insurance = exclude_internal_insurance
    db.commit()
    db.refresh(settings)
    return settings
