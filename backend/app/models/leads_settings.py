"""Connection settings for the website-leads intake (Settings -> Заявки) -
same single-row-per-instance pattern as models/telephony_settings.py.

`intake_token` is deliberately its own secret, not app/core/config.py's
API_TOKEN the frontend/1C use - the site posting leads here is a separate,
less-trusted party (a client-run WordPress install we don't administer), so
a leak of this token should only ever be able to submit leads, never reach
anything else this API can do. Rotatable from Settings without a redeploy,
same reasoning as TelephonySettings' zeon_api_key.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

DEFAULT_STALE_AFTER_DAYS = 7


class LeadsSettings(Base):
    __tablename__ = "leads_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    intake_token: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # A lead with no real (>=5s) outbound call yet still counts as "open"
    # (badge/count) until this many days after it arrived - past that it
    # stops showing as urgent, but stays visible forever on the full
    # "Заявки" page (see services/leads_service.get_open_leads /
    # list_leads). Configurable per operator feedback ("иначе могут висеть
    # вечно") rather than a fixed window like the telephony missed-calls
    # badge's own 2-day one, since a lead shouldn't just be forgotten the
    # way a missed call reasonably ages out fast.
    stale_after_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_STALE_AFTER_DAYS
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LeadsSettings enabled={self.enabled}>"
