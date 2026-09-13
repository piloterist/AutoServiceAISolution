"""Aggregates all v1 routers under a single prefix."""

from fastapi import APIRouter

from app.api.v1.endpoints import import_work_orders, work_orders

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(import_work_orders.router)
api_router.include_router(work_orders.router)
