"""Product user accounts - login/password/role, for the per-user auth and
RBAC layer (see ARCHITECTURE.md on the previous single-shared-login gate
this replaces, and app/services/auth_service.py for password hashing and
login verification).

`role` is one of ROLES below, not free text - RBAC checks (e.g. "only
Админ can reach Settings", see frontend middleware.ts) compare against
these exact names, so unlike WorkOrder.department/status (arbitrary client
data), it's a closed set validated at the schema layer.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ROLE_ADMIN = "Админ"
ROLE_MANAGER = "Управляющий"
ROLE_SERVICE_ADVISOR = "Мастер приёмщик"
ROLE_ACCOUNTANT = "Бухгалтер"
ROLE_EMPLOYEE = "Сотрудник"
ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_SERVICE_ADVISOR, ROLE_ACCOUNTANT, ROLE_EMPLOYEE)

# Matches the `data-theme` attribute value the frontend's CSS/ThemeToggle
# already use (see frontend/components/ThemeToggle.tsx, app/globals.css) -
# deliberately English/technical, not translated like ROLES above, so it
# plugs straight into that attribute with no mapping layer. Baked into the
# session cookie at login (see frontend/lib/auth.ts's SessionUser.theme)
# and applied as the default theme on first load - a manual pick via
# ThemeToggle (stored in the browser's own localStorage) always wins over
# this account-level default once made.
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEMES = (THEME_LIGHT, THEME_DARK)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    login: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    # "<salt_hex>$<pbkdf2_hex>" - see auth_service.hash_password/verify_password.
    # No external hashing dependency (bcrypt/argon2) pulled in for a handful
    # of internal accounts - hashlib.pbkdf2_hmac from the stdlib is enough.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    theme: Mapped[str] = mapped_column(
        String(10), nullable=False, default=THEME_LIGHT, server_default=THEME_LIGHT
    )

    # A user's own default Planner scope (see product brief part 3: "эта
    # страница должна открываться с теми значениями который выбраны для
    # текущего пользователя по умолчанию"). Both nullable - not every role
    # necessarily works in a workshop (e.g. Бухгалтер).
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    workshop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workshops.id", ondelete="SET NULL"), nullable=True
    )
    # Optional - one of planner_constants.REPAIR_TYPE_FILTERS. When set,
    # opening the Кузовной Planner defaults its "Вид ремонта" filter to
    # this value instead of "Все" (product spec, 2026-09-30: "если у
    # пользователя выбрано значение в карточке, то открывать кузовной
    # планер сразу с фильтром по этому полю").
    default_repair_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.login!r} {self.role!r}>"
