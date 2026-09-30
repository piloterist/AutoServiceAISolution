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
    EmployeeOut,
    EmployeeWrite,
    RoleTabVisibilityOut,
    RoleTabVisibilityWrite,
    SlesarkaStatusOut,
    SlesarkaStatusWrite,
    UnmappedSourceDepartmentsOut,
    UserCreate,
    UserOut,
    UserUpdate,
    WorkshopOut,
    WorkshopSourceDepartmentOut,
    WorkshopSourceDepartmentWrite,
    WorkshopWrite,
)
from app.services import admin_service, planner_service

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
        zero_revenue=workshop.zero_revenue,
        target_revenue=workshop.target_revenue,
        target_norm_hours=workshop.target_norm_hours,
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


# ---- Соответствие "строка 1С" -> цех (см. services/cockpit_service.py) -----


def _source_department_out(row, label: str) -> WorkshopSourceDepartmentOut:
    return WorkshopSourceDepartmentOut(
        id=row.id,
        workshop_id=row.workshop_id,
        workshop_label=label,
        source_department=row.source_department,
    )


@router.get("/workshop-source-departments", response_model=list[WorkshopSourceDepartmentOut])
def list_workshop_source_departments(
    db: Session = Depends(get_db),
) -> list[WorkshopSourceDepartmentOut]:
    return [
        _source_department_out(row, label)
        for row, label in admin_service.list_workshop_source_departments(db)
    ]


@router.get("/workshop-source-departments/unmapped", response_model=UnmappedSourceDepartmentsOut)
def list_unmapped_source_departments(db: Session = Depends(get_db)) -> UnmappedSourceDepartmentsOut:
    """1C `department` values seen on real work orders with no Workshop
    mapping yet - what still needs assigning below."""
    return UnmappedSourceDepartmentsOut(values=admin_service.list_unmapped_source_departments(db))


@router.post(
    "/workshop-source-departments",
    response_model=WorkshopSourceDepartmentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_workshop_source_department(
    payload: WorkshopSourceDepartmentWrite, db: Session = Depends(get_db)
) -> WorkshopSourceDepartmentOut:
    try:
        row, label = admin_service.create_workshop_source_department(
            db, workshop_id=payload.workshop_id, source_department=payload.source_department
        )
    except Exception as exc:  # unique source_department violation
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="source_department already mapped to a workshop",
        ) from exc
    return _source_department_out(row, label)


@router.put("/workshop-source-departments/{row_id}", response_model=WorkshopSourceDepartmentOut)
def update_workshop_source_department(
    row_id: uuid.UUID, payload: WorkshopSourceDepartmentWrite, db: Session = Depends(get_db)
) -> WorkshopSourceDepartmentOut:
    try:
        result = admin_service.update_workshop_source_department(
            db, row_id, workshop_id=payload.workshop_id, source_department=payload.source_department
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="source_department already mapped to a workshop",
        ) from exc
    if result is None:
        raise _not_found("Mapping")
    return _source_department_out(*result)


@router.delete("/workshop-source-departments/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workshop_source_department(row_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    if not admin_service.delete_workshop_source_department(db, row_id):
        raise _not_found("Mapping")


# ---- Пользователи ---------------------------------------------------------


def _user_out(user, department_name: str | None) -> UserOut:
    return UserOut(
        id=user.id,
        full_name=user.full_name,
        login=user.login,
        role=user.role,
        theme=user.theme,
        department_id=user.department_id,
        department_name=department_name,
        workshop_id=user.workshop_id,
        default_repair_type=user.default_repair_type,
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
            theme=payload.theme,
            department_id=payload.department_id,
            workshop_id=payload.workshop_id,
            default_repair_type=payload.default_repair_type,
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
            theme=payload.theme,
            department_id=payload.department_id,
            workshop_id=payload.workshop_id,
            default_repair_type=payload.default_repair_type,
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


# ---- Сотрудники ---------------------------------------------------------


def _employee_out(employee, department_name: str | None, workshop_label: str | None) -> EmployeeOut:
    return EmployeeOut(
        id=employee.id,
        full_name=employee.full_name,
        specialty=employee.specialty,
        phone=employee.phone,
        birth_date=employee.birth_date,
        department_id=employee.department_id,
        department_name=department_name,
        workshop_id=employee.workshop_id,
        workshop_label=workshop_label,
    )


@router.get("/employees", response_model=list[EmployeeOut])
def list_employees(db: Session = Depends(get_db)) -> list[EmployeeOut]:
    return [_employee_out(e, dep, ws) for e, dep, ws in admin_service.list_employees(db)]


@router.post("/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def create_employee(payload: EmployeeWrite, db: Session = Depends(get_db)) -> EmployeeOut:
    try:
        payload.validate_specialty()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    employee, dep, ws = admin_service.create_employee(
        db,
        full_name=payload.full_name,
        specialty=payload.specialty,
        phone=payload.phone,
        birth_date=payload.birth_date,
        department_id=payload.department_id,
        workshop_id=payload.workshop_id,
    )
    return _employee_out(employee, dep, ws)


@router.put("/employees/{employee_id}", response_model=EmployeeOut)
def update_employee(
    employee_id: uuid.UUID, payload: EmployeeWrite, db: Session = Depends(get_db)
) -> EmployeeOut:
    try:
        payload.validate_specialty()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    result = admin_service.update_employee(
        db,
        employee_id,
        full_name=payload.full_name,
        specialty=payload.specialty,
        phone=payload.phone,
        birth_date=payload.birth_date,
        department_id=payload.department_id,
        workshop_id=payload.workshop_id,
    )
    if result is None:
        raise _not_found("Employee")
    return _employee_out(*result)


@router.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee(employee_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    if not admin_service.delete_employee(db, employee_id):
        raise _not_found("Employee")


# ---- Права доступа (видимость вкладок по роли) -------------------------


@router.get("/role-tab-visibility", response_model=list[RoleTabVisibilityOut])
def list_role_tab_visibility(db: Session = Depends(get_db)) -> list[RoleTabVisibilityOut]:
    return [
        RoleTabVisibilityOut.model_validate(r) for r in admin_service.list_role_tab_visibility(db)
    ]


@router.post(
    "/role-tab-visibility", response_model=RoleTabVisibilityOut, status_code=status.HTTP_201_CREATED
)
def create_role_tab_visibility(
    payload: RoleTabVisibilityWrite, db: Session = Depends(get_db)
) -> RoleTabVisibilityOut:
    try:
        payload.validate_choices()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    try:
        row = admin_service.create_role_tab_visibility(
            db, role=payload.role, visible_tabs=payload.visible_tabs
        )
    except Exception as exc:  # unique role violation
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Role already configured"
        ) from exc
    return RoleTabVisibilityOut.model_validate(row)


@router.put("/role-tab-visibility/{row_id}", response_model=RoleTabVisibilityOut)
def update_role_tab_visibility(
    row_id: uuid.UUID, payload: RoleTabVisibilityWrite, db: Session = Depends(get_db)
) -> RoleTabVisibilityOut:
    try:
        payload.validate_choices()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    try:
        row = admin_service.update_role_tab_visibility(
            db, row_id, role=payload.role, visible_tabs=payload.visible_tabs
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Role already configured"
        ) from exc
    if row is None:
        raise _not_found("Role tab visibility")
    return RoleTabVisibilityOut.model_validate(row)


@router.delete("/role-tab-visibility/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role_tab_visibility(row_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    if not admin_service.delete_role_tab_visibility(db, row_id):
        raise _not_found("Role tab visibility")


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

# changes fields that store a foreign-key UUID rather than a value a person
# would recognize - see _humanize_changes below on why these get resolved
# to a display name before the log ever reaches the frontend, the same way
# work_order_id/car_description are resolved into the columns above.
_ID_FIELDS = ("employee_id", "status_id", "work_order_id")


def _parse_uuid(value: object) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _collect_referenced_ids(entries: list) -> dict[str, set[uuid.UUID]]:
    ids: dict[str, set[uuid.UUID]] = {field: set() for field in _ID_FIELDS}
    for entry in entries:
        for field, diff in entry.changes.items():
            if field in _ID_FIELDS:
                for raw in (diff.get("old"), diff.get("new")):
                    parsed = _parse_uuid(raw)
                    if parsed is not None:
                        ids[field].add(parsed)
            elif field == "stages":
                for snapshot in (diff.get("old") or []) + (diff.get("new") or []):
                    parsed = _parse_uuid((snapshot or {}).get("employee_id"))
                    if parsed is not None:
                        ids["employee_id"].add(parsed)
    return ids


def _humanize_changes(changes: dict, *, employees: dict, statuses: dict, work_orders: dict) -> dict:
    """Replaces raw employee_id/status_id/work_order_id UUIDs (both on their
    own and inside a BodyCar's `stages` snapshot) with the name a person
    actually recognizes - see models/schedule_audit_log.py's module
    docstring: this table exists to be read on the Settings page, not to be
    a byte-exact mirror of the underlying columns."""

    def resolve(field: str, raw: object) -> object:
        parsed = _parse_uuid(raw)
        if parsed is None:
            return raw
        if field == "employee_id":
            employee = employees.get(parsed)
            return employee.full_name if employee else None
        if field == "status_id":
            status_row = statuses.get(parsed)
            return status_row.name if status_row else None
        if field == "work_order_id":
            work_order = work_orders.get(parsed)
            return work_order.external_number if work_order else None
        return raw

    def resolve_stage_snapshot(snapshot: list[dict] | None) -> list[dict] | None:
        if snapshot is None:
            return None
        return [
            {**stage, "employee_id": resolve("employee_id", stage.get("employee_id"))}
            for stage in snapshot
        ]

    result = {}
    for field, diff in changes.items():
        if field in _ID_FIELDS:
            result[field] = {
                "old": resolve(field, diff.get("old")),
                "new": resolve(field, diff.get("new")),
            }
        elif field == "stages":
            result[field] = {
                "old": resolve_stage_snapshot(diff.get("old")),
                "new": resolve_stage_snapshot(diff.get("new")),
            }
        else:
            result[field] = diff
    return result


@router.get("/audit-log", response_model=list[AuditLogEntryOut])
def list_audit_log(db: Session = Depends(get_db)) -> list[AuditLogEntryOut]:
    entries = admin_service.list_audit_log(db)

    referenced_ids = _collect_referenced_ids(entries)
    work_order_ids = referenced_ids["work_order_id"] | {
        e.work_order_id for e in entries if e.work_order_id is not None
    }
    work_orders = planner_service.work_order_lookup(db, work_order_ids)
    employees = planner_service.employee_lookup(db, referenced_ids["employee_id"])
    statuses = planner_service.status_lookup(db, referenced_ids["status_id"])

    return [
        AuditLogEntryOut(
            id=e.id,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            action=e.action,
            changes=_humanize_changes(
                e.changes, employees=employees, statuses=statuses, work_orders=work_orders
            ),
            actor_name=e.actor_name,
            created_at=e.created_at,
            work_order_number=(
                work_orders[e.work_order_id].external_number
                if e.work_order_id in work_orders
                else None
            ),
            car_description=e.car_description,
        )
        for e in entries
    ]
