"""Which work orders the dashboard-style figures leave out (Settings -> Специфика
PanMotors, "Исключить"): one switch with three values, applied everywhere through
`exclusion_filters` so every tab agrees.

- "none"     - nothing is excluded;
- "internal" - the internal work orders (WorkOrder.is_internal, see internal_order_rules);
- "external" - the insurance ones: repair type == AppSettings.insurance_repair_type
               ("Вид ремонта для страховых"); nothing is excluded until that is set.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_

from app.models.work_order import WorkOrder

MODE_NONE = "none"
MODE_INTERNAL = "internal"
MODE_EXTERNAL = "external"
MODES = (MODE_NONE, MODE_INTERNAL, MODE_EXTERNAL)


@dataclass(frozen=True)
class OrderExclusion:
    mode: str = MODE_NONE
    insurance_repair_type: str | None = None

    def filters(self) -> list:
        if self.mode == MODE_INTERNAL:
            return [WorkOrder.is_internal.is_(False)]
        if self.mode == MODE_EXTERNAL and self.insurance_repair_type:
            # NULL repair_type must stay in - a plain != would drop it.
            return [
                or_(
                    WorkOrder.repair_type.is_(None),
                    WorkOrder.repair_type != self.insurance_repair_type,
                )
            ]
        return []


def order_exclusion(app_settings: Any) -> OrderExclusion:
    """The exclusion configured in AppSettings (duck-typed to avoid a settings import)."""
    return OrderExclusion(
        mode=app_settings.order_exclusion_mode or MODE_NONE,
        insurance_repair_type=app_settings.insurance_repair_type,
    )


def exclusion_filters(exclusion: OrderExclusion | None) -> list:
    return exclusion.filters() if exclusion else []


def exclusion_active(exclusion: OrderExclusion | None) -> bool:
    return bool(exclusion_filters(exclusion))
