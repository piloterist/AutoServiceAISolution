"""Deployment-wide configuration editable from the product's own Settings
page, not just env vars (see app/core/config.py for the deploy-time-only
settings that still require a redeploy to change).

Single-tenant hosted (see ARCHITECTURE.md) - one instance per client, so
there is only ever one row, fixed at id=1. Not a general key-value store;
add a column per setting as they're introduced, same as every other model
in this codebase.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    # ЗаказНаряд.ВидРемонта value that identifies an insurance-company
    # repair - picked from whatever distinct values are actually present in
    # imported work orders (see work_order_query_service.list_repair_types),
    # never hardcoded here. None = not configured yet.
    insurance_repair_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Whether "internal" insurance work orders should be excluded from
    # insurance reporting - exact meaning is a business rule for whatever
    # report reads this setting, not defined here.
    exclude_internal_insurance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # "Специфика PanMotors" group - a separate feature from the two fields
    # above (which drive the older insurance-reporting exclusion). This pair
    # instead gates WorkOrder.is_internal (see
    # services/internal_order_rules.py), a car/VIN-and-org/payer-based
    # detection, not an order-number/repair-type-based one.
    exclude_internal_orders: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Not wired to any filtering logic yet - deliberately inert (see
    # SettingsForm.tsx's "в разработке" caption). Still persisted like any
    # other setting so its checkbox state survives a reload.
    hide_internal_orders: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AppSettings insurance_repair_type={self.insurance_repair_type!r}>"
