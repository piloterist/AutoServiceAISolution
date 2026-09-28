"""Contracts for the Settings page's admin-only tables: Пользователи,
Подразделения, Цеха, Статусы слесарки, and the audit log listing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.employee import SPECIALTIES
from app.models.role_tab_visibility import NAV_TAB_KEYS
from app.models.user import ROLES, THEMES
from app.models.workshop import WEEKDAY_CHOICES, WORKSHOP_TYPES

# ---- Подразделения ----------------------------------------------------


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)


class DepartmentUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=150)


# ---- Цеха ---------------------------------------------------------------


class WorkshopOut(BaseModel):
    id: uuid.UUID
    department_id: uuid.UUID
    department_name: str
    workshop_type: str
    area: Decimal | None
    posts_count: int
    is_default: bool
    start_time: time
    end_time: time
    working_days: list[int]
    # Планирование - см. models/workshop.py.
    zero_revenue: Decimal | None
    target_revenue: Decimal | None
    target_norm_hours: Decimal | None

    model_config = {"from_attributes": True}


class WorkshopWrite(BaseModel):
    department_id: uuid.UUID
    workshop_type: str
    area: Decimal | None = None
    posts_count: int = Field(gt=0)
    is_default: bool = False
    start_time: time
    end_time: time
    working_days: list[int] = Field(min_length=1)
    zero_revenue: Decimal | None = None
    target_revenue: Decimal | None = None
    target_norm_hours: Decimal | None = None

    def validate_choices(self) -> None:
        if self.workshop_type not in WORKSHOP_TYPES:
            raise ValueError(f"workshop_type must be one of {WORKSHOP_TYPES}")
        if any(d not in WEEKDAY_CHOICES for d in self.working_days):
            raise ValueError("working_days must be within 0..6 (Monday..Sunday)")


# ---- Соответствие "строка 1С" -> цех (см. models/workshop_source_department.py) ----


class WorkshopSourceDepartmentOut(BaseModel):
    id: uuid.UUID
    workshop_id: uuid.UUID
    workshop_label: str  # "<Подразделение> — <Тип цеха>", e.g. "Каховка — Кузовной"
    source_department: str


class WorkshopSourceDepartmentWrite(BaseModel):
    workshop_id: uuid.UUID
    source_department: str = Field(min_length=1, max_length=150)


class UnmappedSourceDepartmentsOut(BaseModel):
    values: list[str]


# ---- Пользователи ---------------------------------------------------------


class UserOut(BaseModel):
    id: uuid.UUID
    full_name: str
    login: str
    role: str
    theme: str
    department_id: uuid.UUID | None
    department_name: str | None
    workshop_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=4)
    role: str
    theme: str
    department_id: uuid.UUID | None = None
    workshop_id: uuid.UUID | None = None

    def validate_role(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if self.theme not in THEMES:
            raise ValueError(f"theme must be one of {THEMES}")


class UserUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    login: str = Field(min_length=1, max_length=100)
    # Empty/omitted = keep the existing password.
    password: str | None = Field(default=None, min_length=4)
    role: str
    theme: str
    department_id: uuid.UUID | None = None
    workshop_id: uuid.UUID | None = None

    def validate_role(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if self.theme not in THEMES:
            raise ValueError(f"theme must be one of {THEMES}")


# ---- Сотрудники ---------------------------------------------------------


class EmployeeOut(BaseModel):
    id: uuid.UUID
    full_name: str
    specialty: str
    department_id: uuid.UUID | None
    department_name: str | None
    workshop_id: uuid.UUID | None
    workshop_label: str | None

    model_config = {"from_attributes": True}


class EmployeeWrite(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    specialty: str
    department_id: uuid.UUID | None = None
    workshop_id: uuid.UUID | None = None

    def validate_specialty(self) -> None:
        if self.specialty not in SPECIALTIES:
            raise ValueError(f"specialty must be one of {SPECIALTIES}")


# ---- Права доступа (видимость вкладок по роли) -------------------------


class RoleTabVisibilityOut(BaseModel):
    id: uuid.UUID
    role: str
    visible_tabs: list[str]

    model_config = {"from_attributes": True}


class RoleTabVisibilityWrite(BaseModel):
    role: str
    visible_tabs: list[str] = Field(min_length=1)

    def validate_choices(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if any(tab not in NAV_TAB_KEYS for tab in self.visible_tabs):
            raise ValueError(f"visible_tabs entries must be within {NAV_TAB_KEYS}")


# ---- Статусы слесарки ------------------------------------------------


class SlesarkaStatusOut(BaseModel):
    id: uuid.UUID
    name: str
    color: str

    model_config = {"from_attributes": True}


class SlesarkaStatusWrite(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


# ---- Аудит-лог (read-only) ---------------------------------------------


class AuditLogEntryOut(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    action: str
    changes: dict
    actor_name: str
    created_at: datetime
    # The entity's ЗН/car at the time of the change - see
    # models/schedule_audit_log.py. work_order_number is resolved from
    # work_order_id by the endpoint (not stored), null if the entry has no
    # linked ЗН or that ЗН was since deleted.
    work_order_number: str | None
    car_description: str | None

    model_config = {"from_attributes": True}


# ---- Аутентификация -------------------------------------------------------


class LoginRequest(BaseModel):
    login: str
    password: str


class AuthenticatedUser(BaseModel):
    id: uuid.UUID
    full_name: str
    login: str
    role: str
    theme: str
    department_id: uuid.UUID | None
    department_name: str | None
    workshop_id: uuid.UUID | None
    # Baked in at login time from RoleTabVisibility - see
    # services/admin_service.get_visible_tabs_for_role.
    allowed_tabs: list[str]

    model_config = {"from_attributes": True}
