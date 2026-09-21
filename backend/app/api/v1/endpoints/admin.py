"""CRUD for the Settings page's admin-only tables - see services/admin_service.py.

Same bearer-token protection as the rest of the API; the Next.js middleware
is what actually keeps non-Admin users out of these Settings pages (see
frontend/middleware.ts) - this backend trusts that gate the same way it
already trusts Next.js for everything else (see endpoints/settings.py).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.schemas.admin import (
    AuditLogEntryOut,
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    SlesarkaStatusOut,
    SlesarkaStatusWrite,
    UserCreate,
    UserOut,
    UserUpdate,
    WorkshopOut,
    WorkshopWrite,
)
from app.services import admin_service

router = APIRouter(prefix="/settings", tags=["admin"], dependencies=[Depends(verify_api_token)])


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


# ---- Подразделения ----------------------------------------------------


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(db: Session = Depends(get_db)) -> list[DepartmentOut]:
    return [DepartmentOut.model_validate(d) for d in admin_service.list_departments(db)]


@router.post("/departments", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db)) -> DepartmentOut:
    return DepartmentOut.model_validate(admin_service.create_department(db, name=payload.name))


@router.put("/departments/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: uuid.UUID, payload: DepartmentUpdate, db: Session = Depends(get_db)
) -> DepartmentOut:
    department = admin_service.update_department(db, department_id, name=payload.name)
    if department is None:
        raise _not_found("Department")
    return DepartmentOut.model_validate(department)


@router.delete("/departments/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(department_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    if not admin_service.delete_department(db, department_id):
        raise _not_found("Department")


# ---- Цеха ---------------------------------------------------------------


def _workshop_out(workshop, department_name: str) -> WorkshopOut:
    return WorkshopOut(
        id=workshop.id,
        department_id=workshop.department_id,
        department_name=department_name,
        workshop_type=workshop.workshop_type,
        area=workshop.area,
        posts_count=workshop.posts_count,
        is_default=workshop.is_default,
        start_time=workshop.start_time,
        end_time=workshop.end_time,
        working_days=workshop.working_days,
    )


@router.get("/workshops", response_model=list[WorkshopOut])
def list_workshops(db: Session = Depends(get_db)) -> list[WorkshopOut]:
    return [_workshop_out(w, name) for w, name in admin_service.list_workshops(db)]


@router.post("/workshops", response_model=WorkshopOut, status_code=status.HTTP_201_CREATED)
def create_workshop(payload: WorkshopWrite, db: Session = Depends(get_db)) -> WorkshopOut:
    try:
        payload.validate_choices()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    workshop, department_name = admin_service.create_workshop(db, data=payload.model_dump())
    return _workshop_out(workshop, department_name)


@router.put("/workshops/{workshop_id}", response_model=WorkshopOut)
def update_workshop(
    workshop_id: uuid.UUID, payload: WorkshopWrite, db: Session = Depends(get_db)
) -> WorkshopOut:
    try:
        payload.validate_choices()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    result = admin_service.update_workshop(db, workshop_id, data=payload.model_dump())
    if result is None:
        raise _not_found("Workshop")
    return _workshop_out(*result)


@router.delete("/workshops/{workshop_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workshop(workshop_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    if not admin_service.delete_workshop(db, workshop_id):
        raise _not_found("Workshop")


# ---- Пользователи ---------------------------------------------------------


def _user_out(user, department_name: str | None) -> UserOut:
    return UserOut(
        id=user.id,
        full_name=user.full_name,
        login=user.login,
        role=user.role,
        department_id=user.department_id,
        department_name=department_name,
        workshop_id=user.workshop_id,
    )


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)) -> list[UserOut]:
    return [_user_out(u, name) for u, name in admin_service.list_users(db)]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> UserOut:
    try:
        payload.validate_role()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    try:
        user, department_name = admin_service.create_user(
            db,
            full_name=payload.full_name,
            login=payload.login,
            password=payload.password,
            role=payload.role,
            department_id=payload.department_id,
            workshop_id=payload.workshop_id,
        )
    except Exception as exc:  # unique login violation
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Login already in use"
        ) from exc
    return _user_out(user, department_name)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, payload: UserUpdate, db: Session = Depends(get_db)) -> UserOut:
    try:
        payload.validate_role()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    try:
        result = admin_service.update_user(
            db,
            user_id,
            full_name=payload.full_name,
            login=payload.login,
            password=payload.password,
            role=payload.role,
            department_id=payload.department_id,
            workshop_id=payload.workshop_id,
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Login already in use"
        ) from exc
    if result is None:
        raise _not_found("User")
    return _user_out(*result)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    if not admin_service.delete_user(db, user_id):
        raise _not_found("User")


# ---- Статусы слесарки ------------------------------------------------


@router.get("/slesarka-statuses", response_model=list[SlesarkaStatusOut])
def list_slesarka_statuses(db: Session = Depends(get_db)) -> list[SlesarkaStatusOut]:
    return [SlesarkaStatusOut.model_validate(s) for s in admin_service.list_slesarka_statuses(db)]


@router.post(
    "/slesarka-statuses", response_model=SlesarkaStatusOut, status_code=status.HTTP_201_CREATED
)
def create_slesarka_status(
    payload: SlesarkaStatusWrite, db: Session = Depends(get_db)
) -> SlesarkaStatusOut:
    return SlesarkaStatusOut.model_validate(
        admin_service.create_slesarka_status(db, name=payload.name, color=payload.color)
    )


@router.put("/slesarka-statuses/{status_id}", response_model=SlesarkaStatusOut)
def update_slesarka_status(
    status_id: uuid.UUID, payload: SlesarkaStatusWrite, db: Session = Depends(get_db)
) -> SlesarkaStatusOut:
    result = admin_service.update_slesarka_status(
        db, status_id, name=payload.name, color=payload.color
    )
    if result is None:
        raise _not_found("Status")
    return SlesarkaStatusOut.model_validate(result)


@router.delete("/slesarka-statuses/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_slesarka_status(status_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    if not admin_service.delete_slesarka_status(db, status_id):
        raise _not_found("Status")


# ---- Аудит-лог (read-only) ---------------------------------------------


@router.get("/audit-log", response_model=list[AuditLogEntryOut])
def list_audit_log(db: Session = Depends(get_db)) -> list[AuditLogEntryOut]:
    return [AuditLogEntryOut.model_validate(e) for e in admin_service.list_audit_log(db)]
