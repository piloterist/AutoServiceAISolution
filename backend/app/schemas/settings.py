"""Contract for the product's own editable Settings page (app_settings)."""

from pydantic import BaseModel


class AppSettingsResponse(BaseModel):
    insurance_repair_type: str | None
    exclude_internal_insurance: bool

    model_config = {"from_attributes": True}


class AppSettingsUpdate(BaseModel):
    insurance_repair_type: str | None = None
    exclude_internal_insurance: bool = False
