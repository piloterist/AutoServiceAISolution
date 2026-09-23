"""Per-role top-nav tab visibility - Settings → Пользователи → "Права
доступа". Replaces what used to be a single hardcoded rule (Мастер приёмщик
sees only Планер - see frontend middleware.ts) with a configurable table:
one row per role, listing which of the app's top-nav tabs that role can
reach. A role with no row here is unrestricted (sees every tab) - this is a
fail-open default, deliberately chosen so a missing/not-yet-configured row
never locks staff out.

/settings itself is NOT one of the configurable tabs - it stays hardcoded to
ROLE_ADMIN only (frontend middleware.ts), specifically so a role's own
visible-tabs list can never be edited into a state that locks every admin
out of the page that edits it.
"""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Mirrors frontend/lib/nav-tabs.ts's NAV_TABS keys - kept as plain strings
# (not a hardcoded enum-like closed set at the DB layer) since it's product
# navigation, not client data, but validated against this exact list at the
# schema layer (see schemas/admin.py) the same way User.role is.
NAV_TAB_KEYS = ("/dashboard", "/work-orders", "/planner", "/kanban", "/employees", "/analytics")


class RoleTabVisibility(Base):
    __tablename__ = "role_tab_visibility"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    visible_tabs: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RoleTabVisibility {self.role!r} {self.visible_tabs!r}>"
