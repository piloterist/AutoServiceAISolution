"""API доски задач CRM - see services/crm_task_service.py.

Тот же bearer-токен, что и у остального API; кто нажал кнопку - из заголовков X-Actor-* (их ставит
прокси фронта).
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.api.v1.endpoints.planner import actor
from app.db.session import get_db
from app.models.crm_task import CrmTask
from app.models.employee import Employee
from app.schemas.crm_tasks import (
    CrmTaskActionOut,
    CrmTaskCommentIn,
    CrmTaskCommentOut,
    CrmTaskCreateIn,
    CrmTaskCreateOut,
    CrmTaskDetailOut,
    CrmTaskListResponse,
    CrmTaskMoveIn,
    CrmTaskOut,
    CrmTaskOverdueCountOut,
)
from app.services import admin_service
from app.services import crm_task_service as service
from app.services.settings_service import get_app_settings

router = APIRouter(
    prefix="/crm-tasks", tags=["crm-tasks"], dependencies=[Depends(verify_api_token)]
)


def _http_error(exc: service.CrmTaskError) -> HTTPException:
    if isinstance(exc, service.CrmTaskNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


def _workshop_labels(db: Session) -> dict[uuid.UUID, str]:
    return {
        w.id: f"{department_name} — {w.workshop_type}"
        for w, department_name in admin_service.list_workshops(db)
    }


def _employee_names(db: Session) -> dict[uuid.UUID, str]:
    return {e.id: e.full_name for e in db.scalars(select(Employee))}


def _out(
    task: CrmTask,
    labels: dict[uuid.UUID, str],
    warn_days: int,
    overdue_days: int,
    now: datetime,
    comments_count: int = 0,
    employees: dict[uuid.UUID, str] | None = None,
) -> CrmTaskOut:
    return CrmTaskOut(
        id=task.id,
        phone=task.phone,
        status=task.status,
        status_changed_at=task.status_changed_at,
        call_at=task.call_at,
        workshop_id=task.workshop_id,
        workshop_label=labels.get(task.workshop_id) if task.workshop_id else None,
        next_action_date=task.next_action_date,
        employee_id=task.employee_id,
        employee_name=(employees or {}).get(task.employee_id) if task.employee_id else None,
        client_name=task.client_name,
        car_description=task.car_description,
        request_number=task.request_number,
        work_order_number=task.work_order_number,
        refuse_reason=task.refuse_reason,
        inspection_at=task.inspection_at,
        inspection_date=task.inspection_date,
        inspection_end_date=task.inspection_end_date,
        planner_record=task.body_car_id is not None or task.workshop_job_id is not None,
        planner_record_id=task.body_car_id or task.workshop_job_id,
        created_by_name=task.created_by_name,
        moved_by_name=task.moved_by_name,
        alert=service.alert_for(task, warn_days, overdue_days, now),
        comments_count=comments_count,
    )


@router.get("", response_model=CrmTaskListResponse)
def read_tasks(
    workshop_id: uuid.UUID | None = Query(default=None, description="Только этот цех"),
    employee_id: uuid.UUID | None = Query(default=None, description="Только этот сотрудник"),
    archived: bool = Query(
        default=False, description="Показать и архивные («Отказ»/«Заказ-наряд» старше срока)"
    ),
    db: Session = Depends(get_db),
) -> CrmTaskListResponse:
    tasks = service.list_tasks(
        db, workshop_id=workshop_id, employee_id=employee_id, include_archived=archived
    )
    settings = get_app_settings(db)
    labels = _workshop_labels(db)
    now = datetime.now(UTC)
    warn, overdue = settings.crm_task_warn_days, settings.crm_task_overdue_days
    counts = service.comment_counts(db, [task.id for task in tasks])
    names = _employee_names(db)
    return CrmTaskListResponse(
        warn_days=warn,
        overdue_days=overdue,
        items=[
            _out(task, labels, warn, overdue, now, counts.get(task.id, 0), names) for task in tasks
        ],
    )


@router.get("/overdue-count", response_model=CrmTaskOverdueCountOut)
def read_overdue_count(
    workshop_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CrmTaskOverdueCountOut:
    result = service.overdue_count(db, workshop_id=workshop_id)
    return CrmTaskOverdueCountOut(
        count=result.warn_count,
        overdue_count=result.overdue_count,
        warn_days=result.warn_days,
        overdue_days=result.overdue_days,
    )


@router.post("", response_model=CrmTaskCreateOut)
def create_task(
    payload: CrmTaskCreateIn,
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> CrmTaskCreateOut:
    try:
        task, created = service.create_from_call(
            db,
            payload.call_id,
            workshop_id=payload.workshop_id,
            employee_id=payload.employee_id,
            actor_id=who[0],
            actor_name=who[1],
        )
    except service.CrmTaskError as exc:
        raise _http_error(exc) from exc
    settings = get_app_settings(db)
    return CrmTaskCreateOut(
        task=_out(
            task,
            _workshop_labels(db),
            settings.crm_task_warn_days,
            settings.crm_task_overdue_days,
            datetime.now(UTC),
            employees=_employee_names(db),
        ),
        created=created,
    )


@router.post("/{task_id}/move", response_model=CrmTaskOut)
def move_task(
    task_id: uuid.UUID,
    payload: CrmTaskMoveIn,
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> CrmTaskOut:
    try:
        task = service.move_task(
            db,
            task_id,
            payload.status,
            reason=payload.reason,
            body_car_id=payload.body_car_id,
            workshop_job_id=payload.workshop_job_id,
            actor_id=who[0],
            actor_name=who[1],
        )
    except service.CrmTaskError as exc:
        raise _http_error(exc) from exc
    settings = get_app_settings(db)
    return _out(
        task,
        _workshop_labels(db),
        settings.crm_task_warn_days,
        settings.crm_task_overdue_days,
        datetime.now(UTC),
        service.comment_counts(db, [task.id]).get(task.id, 0),
        _employee_names(db),
    )


def _comment_out(comment) -> CrmTaskCommentOut:
    return CrmTaskCommentOut(
        id=comment.id,
        status=comment.status,
        text=comment.text,
        author_name=comment.author_name,
        created_at=comment.created_at,
    )


@router.get("/{task_id}", response_model=CrmTaskDetailOut)
def read_task(task_id: uuid.UUID, db: Session = Depends(get_db)) -> CrmTaskDetailOut:
    try:
        task = service.get_task(db, task_id)
    except service.CrmTaskError as exc:
        raise _http_error(exc) from exc
    settings = get_app_settings(db)
    comments = service.list_comments(db, task.id)
    request_id, work_order_id = service.linked_document_ids(db, task)
    return CrmTaskDetailOut(
        task=_out(
            task,
            _workshop_labels(db),
            settings.crm_task_warn_days,
            settings.crm_task_overdue_days,
            datetime.now(UTC),
            len(comments),
            _employee_names(db),
        ),
        request_id=request_id,
        work_order_id=work_order_id,
        comments=[_comment_out(comment) for comment in comments],
        actions=[
            CrmTaskActionOut(
                id=action.id,
                planned_date=action.planned_date,
                comment=action.comment,
                author_name=action.author_name,
                created_at=action.created_at,
            )
            for action in service.list_actions(db, task.id)
        ],
    )


@router.post("/{task_id}/comments", response_model=CrmTaskCommentOut)
def add_task_comment(
    task_id: uuid.UUID,
    payload: CrmTaskCommentIn,
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> CrmTaskCommentOut:
    try:
        comment = service.add_comment(
            db,
            task_id,
            payload.text,
            next_action_date=payload.next_action_date,
            actor_id=who[0],
            actor_name=who[1],
        )
    except service.CrmTaskError as exc:
        raise _http_error(exc) from exc
    return _comment_out(comment)
