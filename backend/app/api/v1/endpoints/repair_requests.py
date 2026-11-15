"""API контроля заявок на ремонт - see services/request_control_service.py.

Тот же bearer-токен, что и у остального API. Кто спрашивает (чей цех, есть ли право
дисквалифицировать без попыток), берётся из заголовков X-Actor-* - их ставит прокси фронта.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.api.v1.endpoints.planner import actor
from app.db.session import get_db
from app.schemas.repair_requests import (
    AttemptOut,
    DisqualifyIn,
    ManualAttemptIn,
    OverdueRequestOut,
    OverdueRequestsResponse,
    RequestControlOut,
)
from app.services import request_control_service as control
from app.services.settings_service import get_app_settings

router = APIRouter(
    prefix="/repair-requests", tags=["repair-requests"], dependencies=[Depends(verify_api_token)]
)


def _http_error(exc: control.RequestControlError) -> HTTPException:
    if isinstance(exc, control.RequestNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    if isinstance(exc, control.RequestForbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, control.RequestNotOpen):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


def _control_out(
    db: Session, state: control.RequestState, user_id: uuid.UUID | None
) -> RequestControlOut:
    request = state.request
    settings = get_app_settings(db)
    unchecked = control.can_disqualify_unchecked(db, user_id)
    is_open = state.status == control.STATUS_OPEN
    return RequestControlOut(
        id=request.id,
        status=state.status,
        overdue=state.overdue,
        created_at=state.created_at,
        first_deadline=state.first_deadline,
        second_deadline=state.second_deadline,
        attempts_count=state.attempts_count,
        attempts_required=control.ATTEMPTS_REQUIRED,
        missed_calls=state.missed_calls,
        attempts=[
            AttemptOut(
                at=attempt.at,
                kind=attempt.kind,
                operator=attempt.operator,
                talk_sec=attempt.talk_sec,
                comment=attempt.comment,
                by=attempt.by,
            )
            for attempt in state.attempts
        ],
        disqualified_at=request.request_disqualified_at,
        disqualified_by=request.request_disqualified_by,
        disqualify_reason=request.request_disqualify_reason,
        disqualify_comment=request.request_disqualify_comment,
        can_disqualify=is_open and (state.attempts_count >= control.ATTEMPTS_REQUIRED or unchecked),
        can_disqualify_unchecked=unchecked,
        reasons=list(control.DISQUALIFY_REASONS),
        min_talk_sec=settings.request_min_talk_sec,
        control_enabled=settings.request_control_enabled,
    )


@router.get("/overdue", response_model=OverdueRequestsResponse)
def read_overdue(
    scope: Literal["mine", "all"] = Query(
        default="mine", description="mine - только цех пользователя, all - все цеха (лист «Ошибки»)"
    ),
    workshop_id: uuid.UUID | None = Query(
        default=None,
        description="Только заявки цеха этого планировщика (с scope=mine); "
        "без него - весь цех пользователя",
    ),
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> OverdueRequestsResponse:
    settings = get_app_settings(db)
    departments = None
    if scope == "mine":
        departments = (
            control.departments_for_workshop(db, who[0], workshop_id)
            if workshop_id is not None
            else control.departments_for_user(db, who[0])
        )
    states = control.overdue_states(db, departments=departments)
    items = [
        OverdueRequestOut(
            id=state.request.id,
            external_number=state.request.external_number,
            customer_name=state.request.customer_name,
            phone=state.request.phone,
            vehicle_description=state.request.vehicle_description,
            department=state.request.department,
            created_at=state.created_at,
            overdue=state.overdue,
            deadline=(
                state.first_deadline
                if state.overdue == control.OVERDUE_FIRST
                else state.second_deadline
            ),
            attempts_count=state.attempts_count,
        )
        for state in states
    ]
    return OverdueRequestsResponse(
        enabled=settings.request_control_enabled,
        popup_enabled=settings.request_popup_enabled,
        popup_interval_minutes=settings.request_popup_interval_minutes,
        first_count=sum(1 for item in items if item.overdue == control.OVERDUE_FIRST),
        second_count=sum(1 for item in items if item.overdue == control.OVERDUE_SECOND),
        items=items,
    )


@router.get("/{request_id}/control", response_model=RequestControlOut)
def read_control(
    request_id: uuid.UUID,
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> RequestControlOut:
    try:
        state = control.get_state(db, request_id, now=datetime.now(UTC))
    except control.RequestControlError as exc:
        raise _http_error(exc) from exc
    return _control_out(db, state, who[0])


@router.post("/{request_id}/attempts", response_model=RequestControlOut)
def add_attempt(
    request_id: uuid.UUID,
    payload: ManualAttemptIn,
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> RequestControlOut:
    try:
        state = control.add_manual_attempt(
            db,
            request_id,
            user_id=who[0],
            user_name=who[1],
            comment=payload.comment,
            attempted_at=payload.attempted_at,
        )
    except control.RequestControlError as exc:
        raise _http_error(exc) from exc
    return _control_out(db, state, who[0])


@router.post("/{request_id}/disqualify", response_model=RequestControlOut)
def disqualify_request(
    request_id: uuid.UUID,
    payload: DisqualifyIn,
    who: tuple[uuid.UUID | None, str] = Depends(actor),
    db: Session = Depends(get_db),
) -> RequestControlOut:
    try:
        state = control.disqualify(
            db,
            request_id,
            user_id=who[0],
            user_name=who[1],
            reason=payload.reason,
            comment=payload.comment,
        )
    except control.RequestControlError as exc:
        raise _http_error(exc) from exc
    return _control_out(db, state, who[0])
