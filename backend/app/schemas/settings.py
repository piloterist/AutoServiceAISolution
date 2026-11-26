"""Contract for the product's own editable Settings page (app_settings)."""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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
    order_exclusion_mode: Literal["none", "internal", "external"]
    allocate_external: bool
    receivables_max_age_days: int | None
    hide_internal_orders: bool
    warranty_repair_types: list[str]
    virtual_repair_types: list[str]
    fivesystems_api_enabled: bool
    daily_logout_time: str
    planner_auto_match_enabled: bool
    planner_auto_match_interval_minutes: int
    planner_search_exclude_closed_orders: bool
    cash_lock_from: date | None
    cash_lock_to: date | None
    # Контроль заявок на ремонт - see models/app_settings.py.
    request_control_enabled: bool
    request_first_call_days: int
    request_second_call_days: int
    request_min_talk_sec: int
    request_popup_enabled: bool
    request_popup_interval_minutes: int
    request_auto_disqualify_days: int
    # Доска задач CRM - see models/app_settings.py.
    crm_task_warn_days: int
    crm_task_overdue_days: int
    crm_task_archive_days: int
    # Видеоконтроль: пост закреплён за записью - see models/app_settings.py.
    control_posts_enabled: bool

    model_config = {"from_attributes": True}

    _normalize_warranty_repair_types = field_validator("warranty_repair_types", mode="before")(
        _none_to_empty_list
    )
    _normalize_virtual_repair_types = field_validator("virtual_repair_types", mode="before")(
        _none_to_empty_list
    )


class AppSettingsUpdate(BaseModel):
    insurance_repair_type: str | None = None
    exclude_internal_insurance: bool = False
    order_exclusion_mode: Literal["none", "internal", "external"] = "none"
    allocate_external: bool = False
    receivables_max_age_days: int | None = Field(default=None, ge=1, le=36500)
    hide_internal_orders: bool = False
    warranty_repair_types: list[str] = Field(default_factory=list)
    virtual_repair_types: list[str] = Field(default_factory=list)
    fivesystems_api_enabled: bool = False
    daily_logout_time: str = "23:30"
    planner_auto_match_enabled: bool = False
    planner_auto_match_interval_minutes: int = Field(default=180, gt=0)
    planner_search_exclude_closed_orders: bool = False
    cash_lock_from: date | None = None
    cash_lock_to: date | None = None
    request_control_enabled: bool = False
    request_first_call_days: int = Field(default=3, ge=1, le=365)
    request_second_call_days: int = Field(default=7, ge=1, le=365)
    request_min_talk_sec: int = Field(default=20, ge=1, le=3600)
    request_popup_enabled: bool = True
    request_popup_interval_minutes: int = Field(default=30, ge=1, le=1440)
    request_auto_disqualify_days: int = Field(default=30, ge=1, le=3650)
    crm_task_warn_days: int = Field(default=1, ge=1, le=365)
    crm_task_overdue_days: int = Field(default=3, ge=1, le=365)
    crm_task_archive_days: int = Field(default=30, ge=1, le=3650)
    control_posts_enabled: bool = False

    @model_validator(mode="after")
    def _check_crm_task_days(self) -> "AppSettingsUpdate":
        if self.crm_task_overdue_days < self.crm_task_warn_days:
            raise ValueError("Красный срок доски задач не может быть раньше розового")
        return self

    @model_validator(mode="after")
    def _check_request_days(self) -> "AppSettingsUpdate":
        if self.request_second_call_days < self.request_first_call_days:
            raise ValueError("Срок второго звонка не может быть раньше срока первого")
        if self.request_auto_disqualify_days < self.request_second_call_days:
            raise ValueError("Автодисквалификация не может наступать раньше срока второго звонка")
        return self

    @model_validator(mode="after")
    def _check_cash_lock(self) -> "AppSettingsUpdate":
        if (self.cash_lock_from is None) != (self.cash_lock_to is None):
            raise ValueError("Период блокировки кассы: укажите обе даты или ни одной")
        if (
            self.cash_lock_from is not None
            and self.cash_lock_to is not None
            and self.cash_lock_to < self.cash_lock_from
        ):
            raise ValueError("Период блокировки кассы: дата «по» раньше даты «с»")
        return self

    _validate_daily_logout_time = field_validator("daily_logout_time")(_validate_hhmm)
