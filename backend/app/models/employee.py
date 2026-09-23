"""Сотрудник (employee) - a worker reference row for Settings' own
"Сотрудники" list. Distinct from models/user.py's User: a User is an app
login (auth/RBAC), an Employee is just descriptive staff data (who works
where, in what specialty) - not every employee necessarily has an app
account, and not every User row necessarily corresponds to a floor worker.
No relationship between the two tables is modeled (kept deliberately
separate, same reasoning as WorkOrder.department being free text distinct
from the Department table).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SPECIALTY_SHEET_METAL = "Жестянщик"
SPECIALTY_PAINTER = "Маляр"
SPECIALTY_REBAR = "Арматурщик"
SPECIALTY_MECHANIC = "Механик"
SPECIALTY_SERVICE_ADVISOR = "Мастер приёмщик"
SPECIALTY_ADMINISTRATOR = "Администратор"
SPECIALTIES = (
    SPECIALTY_SHEET_METAL,
    SPECIALTY_PAINTER,
    SPECIALTY_REBAR,
    SPECIALTY_MECHANIC,
    SPECIALTY_SERVICE_ADVISOR,
    SPECIALTY_ADMINISTRATOR,
)


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    specialty: Mapped[str] = mapped_column(String(50), nullable=False)

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
        return f"<Employee {self.full_name!r} {self.specialty!r}>"
