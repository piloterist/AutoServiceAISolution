"""Contracts for the Settings page's admin-only tables: Пользователи,
Подразделения, Цеха, Статусы слесарки, and the audit log listing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.user import ROLES
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

    def validate_choices(self) -> None:
        if self.workshop_type not in WORKSHOP_TYPES:
            raise ValueError(f"workshop_type must be one of {WORKSHOP_TYPES}")
        if any(d not in WEEKDAY_CHOICES for d in self.working_days):
            raise ValueError("working_days must be within 0..6 (Monday..Sunday)")


# ---- Пользователи ---------------------------------------------------------


class UserOut(BaseModel):
    id: uuid.UUID
    full_name: str
    login: str
    role: str
    department_id: uuid.UUID | None
    department_name: str | None
    workshop_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=4)
    role: str
    department_id: uuid.UUID | None = None
    workshop_id: uuid.UUID | None = None

    def validate_role(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")


class UserUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    login: str = Field(min_length=1, max_length=100)
    # Empty/omitted = keep the existing password.
    password: str | None = Field(default=None, min_length=4)
    role: str
    department_id: uuid.UUID | None = None
    workshop_id: uuid.UUID | None = None

    def validate_role(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")


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
    department_id: uuid.UUID | None
    department_name: str | None
    workshop_id: uuid.UUID | None

    model_config = {"from_attributes": True}
