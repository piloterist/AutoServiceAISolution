"""Aggregates all v1 routers under a single prefix."""

from fastapi import APIRouter

from app.api.v1.endpoints import admin, auth, import_work_orders, planner, settings, work_orders

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(import_work_orders.router)
api_router.include_router(work_orders.router)
api_router.include_router(settings.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(planner.router)
