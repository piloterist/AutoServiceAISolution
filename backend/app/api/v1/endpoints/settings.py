"""Read/write API for the product's own Settings page (app_settings).

Same bearer-token protection as the rest of the read API - the frontend's
server proxies these calls, the browser never holds the token directly
(see frontend/lib/backend-api.ts).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.schemas.settings import AppSettingsResponse, AppSettingsUpdate
from app.services.settings_service import get_app_settings, update_app_settings

router = APIRouter(tags=["settings"], dependencies=[Depends(verify_api_token)])


@router.get("/settings", response_model=AppSettingsResponse)
def read_settings(db: Session = Depends(get_db)) -> AppSettingsResponse:
    return AppSettingsResponse.model_validate(get_app_settings(db))


@router.put("/settings", response_model=AppSettingsResponse)
def write_settings(
    payload: AppSettingsUpdate, db: Session = Depends(get_db)
) -> AppSettingsResponse:
    settings = update_app_settings(
        db,
        insurance_repair_type=payload.insurance_repair_type,
        exclude_internal_insurance=payload.exclude_internal_insurance,
        order_exclusion_mode=payload.order_exclusion_mode,
        receivables_max_age_days=payload.receivables_max_age_days,
        hide_internal_orders=payload.hide_internal_orders,
        warranty_repair_types=payload.warranty_repair_types,
        virtual_repair_types=payload.virtual_repair_types,
        fivesystems_api_enabled=payload.fivesystems_api_enabled,
        daily_logout_time=payload.daily_logout_time,
        planner_auto_match_enabled=payload.planner_auto_match_enabled,
        planner_auto_match_interval_minutes=payload.planner_auto_match_interval_minutes,
        planner_search_exclude_closed_orders=payload.planner_search_exclude_closed_orders,
        cash_lock_from=payload.cash_lock_from,
        cash_lock_to=payload.cash_lock_to,
    )
    return AppSettingsResponse.model_validate(settings)
