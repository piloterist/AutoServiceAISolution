"""Contracts for the Planner (Слесарный/Кузовной цех) - see
services/planner_service.py and models/workshop_job.py, models/body_car.py.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.planner_constants import BODY_STAGE_TYPES, CAR_STATUSES

# ---- ЗН autocomplete (used by both dialogs) --------------------------------


class WorkOrderSearchResult(BaseModel):
    id: uuid.UUID
    external_number: str
    vehicle_description: str | None
    vin: str | None
    customer_name: str | None
    phone: str | None
    amount: Decimal

    model_config = {"from_attributes": True}


# ---- Слесарный (WorkshopJob) -----------------------------------------------


class WorkshopJobOut(BaseModel):
    id: uuid.UUID
    workshop_id: uuid.UUID
    work_order_id: uuid.UUID | None
    work_order_number: str | None
    # ЗН.Статус (1C), e.g. "Закрыт" - drives the day header's "Факт" total
    # (product brief: "Факт по заказ-нарядам которые прошли и получили
    # статус Закрыт"), distinct from status_id/status_name below (the
    # Слесарный-record's own SlesarkaStatus).
    work_order_status: str | None
    amount: Decimal | None  # live from the linked ЗН, never stored - see model docstring
    car_description: str | None
    vin: str | None
    plate: str | None
    client_name: str | None
    phone: str | None
    work_description: str | None
    job_date: date
    post_number: int
    start_time: time
    end_time: time
    norm_hours: Decimal | None
    status_id: uuid.UUID | None
    status_name: str | None
    status_color: str | None
    employee_id: uuid.UUID | None
    # Resolved from employee_id - see services/planner_service.employee_lookup.
    employee_name: str | None

    model_config = {"from_attributes": True}


class WorkshopJobWrite(BaseModel):
    work_order_id: uuid.UUID | None = None
    car_description: str | None = None
    vin: str | None = None
    plate: str | None = None
    client_name: str | None = None
    phone: str | None = None
    employee_id: uuid.UUID | None = None
    work_description: str | None = None
    job_date: date
    post_number: int = Field(gt=0)
    start_time: time
    end_time: time
    norm_hours: Decimal | None = None
    status_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check_times(self) -> WorkshopJobWrite:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


# ---- Кузовной (BodyCar + BodyCarStage) -------------------------------------


class BodyCarStageWrite(BaseModel):
    stage_name: str
    note: str | None = None
    start_date: date
    end_date: date
    employee_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> BodyCarStageWrite:
        if self.stage_name not in BODY_STAGE_TYPES:
            raise ValueError(f"stage_name must be one of {BODY_STAGE_TYPES}")
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class BodyCarStageOut(BodyCarStageWrite):
    id: uuid.UUID
    # Resolved from employee_id - see services/planner_service.employee_lookup.
    employee_name: str | None = None

    model_config = {"from_attributes": True}


class BodyCarOut(BaseModel):
    id: uuid.UUID
    workshop_id: uuid.UUID
    work_order_id: uuid.UUID | None
    work_order_number: str | None
    amount: Decimal | None
    car_description: str | None
    vin: str | None
    plate: str | None
    client_name: str | None
    phone: str | None
    work_description: str | None
    color: str
    status: str
    on_site: bool
    stages: list[BodyCarStageOut]
    # Sort key for the car list (product ask: earliest-created first among
    # cars with a stage covering today, latest-created first among the
    # rest) - see BodyView.tsx.
    created_at: datetime

    model_config = {"from_attributes": True}


class BodyCarWrite(BaseModel):
    work_order_id: uuid.UUID | None = None
    car_description: str | None = None
    vin: str | None = None
    plate: str | None = None
    client_name: str | None = None
    phone: str | None = None
    work_description: str | None = None
    status: str
    on_site: bool = False
    stages: list[BodyCarStageWrite] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> BodyCarWrite:
        if self.status not in CAR_STATUSES:
            raise ValueError(f"status must be one of {CAR_STATUSES}")
        # "Проверять, что выбранные даты строк позже не раньше даты строки
        # которая выше" - each stage's start must not precede the previous
        # stage's start (rows may still share a date).
        for previous, current in zip(self.stages, self.stages[1:], strict=False):
            if current.start_date < previous.start_date:
                raise ValueError("stage dates must not go backwards row by row")
        return self
