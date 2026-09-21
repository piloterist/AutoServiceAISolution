"""Planner (Слесарный/Кузовной цех) - see services/planner_service.py.

Same bearer-token protection as the rest of the API. The acting user for
audit logging comes from X-Actor-User-Id/X-Actor-Name headers, set by the
Next.js proxy from the caller's own session cookie (see
frontend/app/api/planner/*/route.ts) - the backend has no session of its
own, same trust boundary as everywhere else here (see endpoints/admin.py).
"""

import uuid
from datetime import date
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.models.body_car import BodyCar
from app.models.workshop_job import WorkshopJob
from app.schemas.planner import (
    BodyCarOut,
    BodyCarStageOut,
    BodyCarWrite,
    WorkOrderSearchResult,
    WorkshopJobOut,
    WorkshopJobWrite,
)
from app.services import planner_service
from app.services.planner_service import NotFoundError, SchedulingError

router = APIRouter(prefix="/planner", tags=["planner"], dependencies=[Depends(verify_api_token)])


def actor(
    x_actor_user_id: str | None = Header(default=None),
    # percent-encoded by the Next.js proxy (see frontend/lib/planner-actor.ts) -
    # raw header VALUES are ASCII/Latin-1-only in both the Fetch API and
    # httpx, and actor names here are routinely Cyrillic.
    x_actor_name: str | None = Header(default=None),
) -> tuple[uuid.UUID | None, str]:
    user_id = None
    if x_actor_user_id:
        try:
            user_id = uuid.UUID(x_actor_user_id)
        except ValueError:
            user_id = None
    return user_id, unquote(x_actor_name) if x_actor_name else "Неизвестно"


@router.get("/work-orders/search", response_model=list[WorkOrderSearchResult])
def search_work_orders(q: str, db: Session = Depends(get_db)) -> list[WorkOrderSearchResult]:
    if not q or len(q.strip()) < 2:
        return []
    return [
        WorkOrderSearchResult.model_validate(w)
        for w in planner_service.search_work_orders(db, q.strip())
    ]


# ---- Слесарный --------------------------------------------------------------


def _job_out(db: Session, job: WorkshopJob) -> WorkshopJobOut:
    work_order = planner_service.work_order_lookup(
        db, {job.work_order_id} if job.work_order_id else set()
    ).get(job.work_order_id)
    status_row = planner_service.status_lookup(db, {job.status_id} if job.status_id else set()).get(
        job.status_id
    )
    return WorkshopJobOut(
        id=job.id,
        workshop_id=job.workshop_id,
        work_order_id=job.work_order_id,
        work_order_number=work_order.external_number if work_order else None,
        amount=work_order.amount if work_order else None,
        car_description=job.car_description,
        vin=job.vin,
        plate=job.plate,
        client_name=job.client_name,
        work_description=job.work_description,
        job_date=job.job_date,
        post_number=job.post_number,
        start_time=job.start_time,
        end_time=job.end_time,
        norm_hours=job.norm_hours,
        status_id=job.status_id,
        status_name=status_row.name if status_row else None,
        status_color=status_row.color if status_row else None,
    )


@router.get("/workshops/{workshop_id}/jobs", response_model=list[WorkshopJobOut])
def list_jobs(
    workshop_id: uuid.UUID, date_from: date, date_to: date, db: Session = Depends(get_db)
) -> list[WorkshopJobOut]:
    jobs = planner_service.list_workshop_jobs(db, workshop_id, date_from=date_from, date_to=date_to)
    return [_job_out(db, j) for j in jobs]


@router.post(
    "/workshops/{workshop_id}/jobs",
    response_model=WorkshopJobOut,
    status_code=status.HTTP_201_CREATED,
)
def create_job(
    workshop_id: uuid.UUID,
    payload: WorkshopJobWrite,
    db: Session = Depends(get_db),
    who: tuple[uuid.UUID | None, str] = Depends(actor),
) -> WorkshopJobOut:
    try:
        job = planner_service.create_workshop_job(
            db, workshop_id, payload, actor_user_id=who[0], actor_name=who[1]
        )
    except SchedulingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _job_out(db, job)


@router.put("/jobs/{job_id}", response_model=WorkshopJobOut)
def update_job(
    job_id: uuid.UUID,
    payload: WorkshopJobWrite,
    db: Session = Depends(get_db),
    who: tuple[uuid.UUID | None, str] = Depends(actor),
) -> WorkshopJobOut:
    try:
        job = planner_service.update_workshop_job(
            db, job_id, payload, actor_user_id=who[0], actor_name=who[1]
        )
    except SchedulingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _job_out(db, job)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    who: tuple[uuid.UUID | None, str] = Depends(actor),
) -> None:
    try:
        planner_service.delete_workshop_job(db, job_id, actor_user_id=who[0], actor_name=who[1])
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ---- Кузовной -----------------------------------------------------------


def _car_out(db: Session, car: BodyCar) -> BodyCarOut:
    work_order = planner_service.work_order_lookup(
        db, {car.work_order_id} if car.work_order_id else set()
    ).get(car.work_order_id)
    return BodyCarOut(
        id=car.id,
        workshop_id=car.workshop_id,
        work_order_id=car.work_order_id,
        work_order_number=work_order.external_number if work_order else None,
        amount=work_order.amount if work_order else None,
        car_description=car.car_description,
        vin=car.vin,
        plate=car.plate,
        client_name=car.client_name,
        work_description=car.work_description,
        color=car.color,
        status=car.status,
        stages=[BodyCarStageOut.model_validate(s) for s in car.stages],
    )


@router.get("/workshops/{workshop_id}/cars", response_model=list[BodyCarOut])
def list_cars(workshop_id: uuid.UUID, db: Session = Depends(get_db)) -> list[BodyCarOut]:
    return [_car_out(db, c) for c in planner_service.list_body_cars(db, workshop_id)]


@router.post(
    "/workshops/{workshop_id}/cars", response_model=BodyCarOut, status_code=status.HTTP_201_CREATED
)
def create_car(
    workshop_id: uuid.UUID,
    payload: BodyCarWrite,
    db: Session = Depends(get_db),
    who: tuple[uuid.UUID | None, str] = Depends(actor),
) -> BodyCarOut:
    car = planner_service.create_body_car(
        db, workshop_id, payload, actor_user_id=who[0], actor_name=who[1]
    )
    return _car_out(db, car)


@router.put("/cars/{car_id}", response_model=BodyCarOut)
def update_car(
    car_id: uuid.UUID,
    payload: BodyCarWrite,
    db: Session = Depends(get_db),
    who: tuple[uuid.UUID | None, str] = Depends(actor),
) -> BodyCarOut:
    try:
        car = planner_service.update_body_car(
            db, car_id, payload, actor_user_id=who[0], actor_name=who[1]
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _car_out(db, car)


@router.delete("/cars/{car_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_car(
    car_id: uuid.UUID,
    db: Session = Depends(get_db),
    who: tuple[uuid.UUID | None, str] = Depends(actor),
) -> None:
    try:
        planner_service.delete_body_car(db, car_id, actor_user_id=who[0], actor_name=who[1])
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
