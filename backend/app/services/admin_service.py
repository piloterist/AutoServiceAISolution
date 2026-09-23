"""CRUD for the Settings page's admin-only tables (Пользователи,
Подразделения, Цеха, Статусы слесарки) and audit log listing.

Thin by design - each function does one query/mutation and commits; the
uniqueness/role/workshop_type validation lives in the Pydantic schemas
(schemas/admin.py) and is called explicitly here before writing, same
pattern as the rest of this codebase's services.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.employee import Employee
from app.models.role_tab_visibility import NAV_TAB_KEYS, RoleTabVisibility
from app.models.schedule_audit_log import ScheduleAuditLog
from app.models.slesarka_status import SlesarkaStatus
from app.models.user import User
from app.models.workshop import Workshop
from app.services import auth_service

# ---- Подразделения ----------------------------------------------------


def list_departments(db: Session) -> list[Department]:
    return list(db.scalars(select(Department).order_by(Department.name)))


def create_department(db: Session, *, name: str) -> Department:
    department = Department(name=name.strip())
    db.add(department)
    db.commit()
    db.refresh(department)
    return department


def update_department(db: Session, department_id: uuid.UUID, *, name: str) -> Department | None:
    department = db.get(Department, department_id)
    if department is None:
        return None
    department.name = name.strip()
    db.commit()
    db.refresh(department)
    return department


def delete_department(db: Session, department_id: uuid.UUID) -> bool:
    department = db.get(Department, department_id)
    if department is None:
        return False
    db.delete(department)
    db.commit()
    return True


# ---- Цеха ---------------------------------------------------------------


def _workshop_with_department_name(db: Session, workshop: Workshop) -> tuple[Workshop, str]:
    department = db.get(Department, workshop.department_id)
    return workshop, department.name if department else ""


def list_workshops(db: Session) -> list[tuple[Workshop, str]]:
    workshops = db.scalars(select(Workshop).order_by(Workshop.workshop_type)).all()
    return [_workshop_with_department_name(db, w) for w in workshops]


def create_workshop(db: Session, *, data: dict) -> tuple[Workshop, str]:
    workshop = Workshop(**data)
    db.add(workshop)
    db.commit()
    db.refresh(workshop)
    return _workshop_with_department_name(db, workshop)


def update_workshop(
    db: Session, workshop_id: uuid.UUID, *, data: dict
) -> tuple[Workshop, str] | None:
    workshop = db.get(Workshop, workshop_id)
    if workshop is None:
        return None
    for key, value in data.items():
        setattr(workshop, key, value)
    db.commit()
    db.refresh(workshop)
    return _workshop_with_department_name(db, workshop)


def delete_workshop(db: Session, workshop_id: uuid.UUID) -> bool:
    workshop = db.get(Workshop, workshop_id)
    if workshop is None:
        return False
    db.delete(workshop)
    db.commit()
    return True


# ---- Пользователи ---------------------------------------------------------


def _user_with_department_name(db: Session, user: User) -> tuple[User, str | None]:
    if user.department_id is None:
        return user, None
    department = db.get(Department, user.department_id)
    return user, department.name if department else None


def list_users(db: Session) -> list[tuple[User, str | None]]:
    users = db.scalars(select(User).order_by(User.full_name)).all()
    return [_user_with_department_name(db, u) for u in users]


def create_user(
    db: Session,
    *,
    full_name: str,
    login: str,
    password: str,
    role: str,
    department_id: uuid.UUID | None,
    workshop_id: uuid.UUID | None,
) -> tuple[User, str | None]:
    user = User(
        full_name=full_name.strip(),
        login=login.strip(),
        password_hash=auth_service.hash_password(password),
        role=role,
        department_id=department_id,
        workshop_id=workshop_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_with_department_name(db, user)


def update_user(
    db: Session,
    user_id: uuid.UUID,
    *,
    full_name: str,
    login: str,
    password: str | None,
    role: str,
    department_id: uuid.UUID | None,
    workshop_id: uuid.UUID | None,
) -> tuple[User, str | None] | None:
    user = db.get(User, user_id)
    if user is None:
        return None
    user.full_name = full_name.strip()
    user.login = login.strip()
    if password:
        user.password_hash = auth_service.hash_password(password)
    user.role = role
    user.department_id = department_id
    user.workshop_id = workshop_id
    db.commit()
    db.refresh(user)
    return _user_with_department_name(db, user)


def delete_user(db: Session, user_id: uuid.UUID) -> bool:
    user = db.get(User, user_id)
    if user is None:
        return False
    db.delete(user)
    db.commit()
    return True


# ---- Сотрудники ---------------------------------------------------------


def _employee_with_names(
    db: Session, employee: Employee
) -> tuple[Employee, str | None, str | None]:
    department_name = None
    if employee.department_id is not None:
        department = db.get(Department, employee.department_id)
        department_name = department.name if department else None

    workshop_label = None
    if employee.workshop_id is not None:
        workshop = db.get(Workshop, employee.workshop_id)
        if workshop is not None:
            w_department = db.get(Department, workshop.department_id)
            w_department_name = w_department.name if w_department else ""
            workshop_label = f"{w_department_name} / {workshop.workshop_type}"

    return employee, department_name, workshop_label


def list_employees(db: Session) -> list[tuple[Employee, str | None, str | None]]:
    employees = db.scalars(select(Employee).order_by(Employee.full_name)).all()
    return [_employee_with_names(db, e) for e in employees]


def create_employee(
    db: Session,
    *,
    full_name: str,
    specialty: str,
    department_id: uuid.UUID | None,
    workshop_id: uuid.UUID | None,
) -> tuple[Employee, str | None, str | None]:
    employee = Employee(
        full_name=full_name.strip(),
        specialty=specialty,
        department_id=department_id,
        workshop_id=workshop_id,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return _employee_with_names(db, employee)


def update_employee(
    db: Session,
    employee_id: uuid.UUID,
    *,
    full_name: str,
    specialty: str,
    department_id: uuid.UUID | None,
    workshop_id: uuid.UUID | None,
) -> tuple[Employee, str | None, str | None] | None:
    employee = db.get(Employee, employee_id)
    if employee is None:
        return None
    employee.full_name = full_name.strip()
    employee.specialty = specialty
    employee.department_id = department_id
    employee.workshop_id = workshop_id
    db.commit()
    db.refresh(employee)
    return _employee_with_names(db, employee)


def delete_employee(db: Session, employee_id: uuid.UUID) -> bool:
    employee = db.get(Employee, employee_id)
    if employee is None:
        return False
    db.delete(employee)
    db.commit()
    return True


# ---- Права доступа (видимость вкладок по роли) -------------------------


def list_role_tab_visibility(db: Session) -> list[RoleTabVisibility]:
    return list(db.scalars(select(RoleTabVisibility).order_by(RoleTabVisibility.role)))


def create_role_tab_visibility(
    db: Session, *, role: str, visible_tabs: list[str]
) -> RoleTabVisibility:
    row = RoleTabVisibility(role=role, visible_tabs=visible_tabs)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_role_tab_visibility(
    db: Session, row_id: uuid.UUID, *, role: str, visible_tabs: list[str]
) -> RoleTabVisibility | None:
    row = db.get(RoleTabVisibility, row_id)
    if row is None:
        return None
    row.role = role
    row.visible_tabs = visible_tabs
    db.commit()
    db.refresh(row)
    return row


def delete_role_tab_visibility(db: Session, row_id: uuid.UUID) -> bool:
    row = db.get(RoleTabVisibility, row_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def get_visible_tabs_for_role(db: Session, role: str) -> list[str]:
    """Baked into the session cookie at login (see endpoints/auth.py) so the
    Edge middleware can enforce it without a DB round trip - same reasoning
    as the cookie carrying `role` itself. A role with no configured row here
    is fail-open (sees every tab), not fail-closed - a missing/not-yet-
    configured row must never silently lock staff out."""
    row = db.scalar(select(RoleTabVisibility).where(RoleTabVisibility.role == role))
    return list(row.visible_tabs) if row is not None else list(NAV_TAB_KEYS)


# ---- Статусы слесарки ------------------------------------------------


def list_slesarka_statuses(db: Session) -> list[SlesarkaStatus]:
    return list(db.scalars(select(SlesarkaStatus).order_by(SlesarkaStatus.name)))


def create_slesarka_status(db: Session, *, name: str, color: str) -> SlesarkaStatus:
    status = SlesarkaStatus(name=name.strip(), color=color)
    db.add(status)
    db.commit()
    db.refresh(status)
    return status


def update_slesarka_status(
    db: Session, status_id: uuid.UUID, *, name: str, color: str
) -> SlesarkaStatus | None:
    status = db.get(SlesarkaStatus, status_id)
    if status is None:
        return None
    status.name = name.strip()
    status.color = color
    db.commit()
    db.refresh(status)
    return status


def delete_slesarka_status(db: Session, status_id: uuid.UUID) -> bool:
    status = db.get(SlesarkaStatus, status_id)
    if status is None:
        return False
    db.delete(status)
    db.commit()
    return True


# ---- Аудит-лог (read-only) ---------------------------------------------


def list_audit_log(db: Session, *, limit: int = 200) -> list[ScheduleAuditLog]:
    stmt = select(ScheduleAuditLog).order_by(ScheduleAuditLog.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))
