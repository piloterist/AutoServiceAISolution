"""Contract for the product's own editable Settings page (app_settings)."""

import re

from pydantic import BaseModel, Field, field_validator

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_hhmm(value: str) -> str:
    if not _HHMM_RE.match(value):
        raise ValueError("Ожидается время в формате ЧЧ:ММ")
    return value


def _none_to_empty_list(value: list[str] | None) -> list[str]:
    """The ORM column is nullable (NULL until anyone ever saves this
    setting) - the API contract is a plain list either way, same as every
    other not-yet-configured list in this codebase."""
    return value or []


class AppSettingsResponse(BaseModel):
    insurance_repair_type: str | None
    exclude_internal_insurance: bool
    # "Специфика PanMotors" group - see models/app_settings.py.
    exclude_internal_orders: bool
    hide_internal_orders: bool
    warranty_repair_types: list[str]
    fivesystems_api_enabled: bool
    daily_logout_time: str
    planner_auto_match_enabled: bool
    planner_auto_match_interval_minutes: int
    planner_search_exclude_closed_orders: bool

    model_config = {"from_attributes": True}

    _normalize_warranty_repair_types = field_validator("warranty_repair_types", mode="before")(
        _none_to_empty_list
    )


class AppSettingsUpdate(BaseModel):
    insurance_repair_type: str | None = None
    exclude_internal_insurance: bool = False
    exclude_internal_orders: bool = False
    hide_internal_orders: bool = False
    warranty_repair_types: list[str] = Field(default_factory=list)
    fivesystems_api_enabled: bool = False
    daily_logout_time: str = "23:30"
    planner_auto_match_enabled: bool = False
    planner_auto_match_interval_minutes: int = Field(default=180, gt=0)
    planner_search_exclude_closed_orders: bool = False

    _validate_daily_logout_time = field_validator("daily_logout_time")(_validate_hhmm)
