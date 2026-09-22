"""Contract for the product's own editable Settings page (app_settings)."""

from pydantic import BaseModel


class AppSettingsResponse(BaseModel):
    insurance_repair_type: str | None
    exclude_internal_insurance: bool
    # "Специфика PanMotors" group - see models/app_settings.py.
    exclude_internal_orders: bool
    hide_internal_orders: bool
    fivesystems_api_enabled: bool

    model_config = {"from_attributes": True}


class AppSettingsUpdate(BaseModel):
    insurance_repair_type: str | None = None
    exclude_internal_insurance: bool = False
    exclude_internal_orders: bool = False
    hide_internal_orders: bool = False
    fivesystems_api_enabled: bool = False
