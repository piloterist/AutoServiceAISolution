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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.login!r} {self.role!r}>"
