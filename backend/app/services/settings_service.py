"""Read/write access to the single app_settings row - see models/app_settings.py."""

from __future__ import annotations

from datetime import date

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
    order_exclusion_mode: str,
    hide_internal_orders: bool,
    warranty_repair_types: list[str],
    fivesystems_api_enabled: bool,
    daily_logout_time: str,
    planner_auto_match_enabled: bool,
    planner_auto_match_interval_minutes: int,
    planner_search_exclude_closed_orders: bool,
    virtual_repair_types: list[str] | None = None,
    cash_lock_from: date | None = None,
    cash_lock_to: date | None = None,
    receivables_max_age_days: int | None = None,
    request_control_enabled: bool = False,
    request_first_call_days: int = 3,
    request_second_call_days: int = 7,
    request_min_talk_sec: int = 20,
    request_popup_enabled: bool = True,
    request_popup_interval_minutes: int = 30,
    request_auto_disqualify_days: int = 30,
    crm_task_warn_days: int = 1,
    crm_task_overdue_days: int = 3,
    crm_task_archive_days: int = 30,
) -> AppSettings:
    settings = get_app_settings(db)
    settings.insurance_repair_type = insurance_repair_type
    settings.exclude_internal_insurance = exclude_internal_insurance
    settings.order_exclusion_mode = order_exclusion_mode
    settings.receivables_max_age_days = receivables_max_age_days or None
    settings.hide_internal_orders = hide_internal_orders
    settings.warranty_repair_types = warranty_repair_types or None
    settings.virtual_repair_types = virtual_repair_types or None
    settings.fivesystems_api_enabled = fivesystems_api_enabled
    settings.daily_logout_time = daily_logout_time
    settings.planner_auto_match_enabled = planner_auto_match_enabled
    settings.planner_auto_match_interval_minutes = planner_auto_match_interval_minutes
    settings.planner_search_exclude_closed_orders = planner_search_exclude_closed_orders
    settings.cash_lock_from = cash_lock_from
    settings.cash_lock_to = cash_lock_to
    settings.request_control_enabled = request_control_enabled
    settings.request_first_call_days = request_first_call_days
    settings.request_second_call_days = request_second_call_days
    settings.request_min_talk_sec = request_min_talk_sec
    settings.request_popup_enabled = request_popup_enabled
    settings.request_popup_interval_minutes = request_popup_interval_minutes
    settings.request_auto_disqualify_days = request_auto_disqualify_days
    settings.crm_task_warn_days = crm_task_warn_days
    settings.crm_task_overdue_days = crm_task_overdue_days
    settings.crm_task_archive_days = crm_task_archive_days
    db.commit()
    db.refresh(settings)
    return settings


def revenue_excluded_repair_types(settings: AppSettings) -> list[str]:
    """Repair types that never count as revenue, on any tab: Гарантийные and
    Виртуальные (Settings -> Общие), without duplicates."""
    return list(
        dict.fromkeys(
            [*(settings.warranty_repair_types or []), *(settings.virtual_repair_types or [])]
        )
    )
