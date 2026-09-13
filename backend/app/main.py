"""FastAPI application entrypoint.

Deliberately thin: configuration, logging, error handling and routers are
each defined in their own module (see app/core, app/api) so the app stays a
modular monolith rather than a single growing file.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import configure_logging
from app.services import yandex_relay

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Optional module, off by default - see app/services/yandex_relay.py for
    # why this exists. Runs as a plain asyncio background task in this same
    # process; no extra service/queue/process to deploy or operate.
    background_task = None
    if settings.enable_yandex_relay:
        background_task = asyncio.create_task(yandex_relay.run_relay_loop())

    yield

    if background_task is not None:
        background_task.cancel()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health_router)
app.include_router(api_router)
