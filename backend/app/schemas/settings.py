"""Contract for the product's own editable Settings page (app_settings)."""

import re

from pydantic import BaseModel, Field, field_validator

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_hhmm(value: str) -> str:
    if not _HHMM_RE.match(value):
        raise ValueError("Ожидается время в формате ЧЧ:ММ")
    return value


class AppSettingsResponse(BaseModel):
    insurance_repair_type: str | None
    exclude_internal_insurance: bool
    # "Специфика PanMotors" group - see models/app_settings.py.
    exclude_internal_orders: bool
    hide_internal_orders: bool
    fivesystems_api_enabled: bool
    daily_logout_time: str
    planner_auto_match_enabled: bool
    planner_auto_match_interval_minutes: int
    planner_search_exclude_closed_orders: bool

    model_config = {"from_attributes": True}


class AppSettingsUpdate(BaseModel):
    insurance_repair_type: str | None = None
    exclude_internal_insurance: bool = False
    exclude_internal_orders: bool = False
    hide_internal_orders: bool = False
    fivesystems_api_enabled: bool = False
    daily_logout_time: str = "23:30"
    planner_auto_match_enabled: bool = False
    planner_auto_match_interval_minutes: int = Field(default=180, gt=0)
    planner_search_exclude_closed_orders: bool = False

    _validate_daily_logout_time = field_validator("daily_logout_time")(_validate_hhmm)
