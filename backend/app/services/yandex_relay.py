"""Optional module: Yandex.Disk relay.

Fallback ingestion path for client networks where 1C's outbound HTTPS is
firewalled against reaching this backend directly (see ARCHITECTURE.md /
DEPLOYMENT.md for why this exists - the Pan Motors / 5Systems hosting blocks
outbound to arbitrary "cloud hosting" IP ranges, Railway included, but not to
Yandex's own infrastructure). 1C uploads its export JSON to a folder on
Yandex.Disk via WebDAV instead of calling this API directly; this module
polls that folder and imports any new file through the exact same
`process_work_order_import` path the direct API uses, then moves the file to
a "processed" subfolder so it is not re-imported (re-importing it would be
harmless - the upsert is idempotent - this is just to avoid repeated work).

Entirely optional and off by default (`ENABLE_YANDEX_RELAY=false`) - a client
whose network reaches this backend directly never needs it. No new
infrastructure: this runs as a background task inside the existing backend
process, not a separate service/queue.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import structlog
from pydantic import ValidationError

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.schemas.import_work_order import ImportWorkOrdersRequest
from app.services.import_service import ImportProcessingError, process_work_order_import

logger = structlog.get_logger(__name__)

YANDEX_API_BASE = "https://cloud-api.yandex.net/v1/disk"
REQUEST_TIMEOUT_SECONDS = 30.0


def select_pending_files(items: list[dict]) -> list[dict]:
    """Pure filter: which listing entries are files we should try to import.

    Kept separate from the network calls so it is trivially unit-testable.
    Excludes subfolders (e.g. the "processed" folder itself, which shows up
    as a sibling entry of type "dir" in the same listing).
    """
    return [item for item in items if item.get("type") == "file"]


def _processed_path(watch_path: str, file_path: str) -> str:
    name = file_path.rsplit("/", 1)[-1]
    return f"{watch_path.rstrip('/')}/processed/{name}"


async def _ensure_folder_exists(client: httpx.AsyncClient, path: str) -> None:
    response = await client.put(f"{YANDEX_API_BASE}/resources", params={"path": path})
    # 409 = already exists, which is the expected steady-state case.
    if response.status_code not in (201, 409):
        logger.warning(
            "yandex_relay_ensure_folder_unexpected_status",
            path=path,
            status_code=response.status_code,
            body=response.text[:500],
        )


async def _ensure_watch_folders_exist(client: httpx.AsyncClient, watch_path: str) -> None:
    # 1C uploads directly into `watch_path` via WebDAV PUT, which - like most
    # WebDAV servers - does not auto-create missing parent directories, so
    # this folder must exist before 1C's first upload. Create the parent
    # before the "processed" subfolder - creating the child first would 409
    # for the wrong reason (missing parent, not "already exists").
    watch_path = watch_path.rstrip("/")
    await _ensure_folder_exists(client, watch_path)
    await _ensure_folder_exists(client, f"{watch_path}/processed")


async def _list_files(client: httpx.AsyncClient, watch_path: str) -> list[dict]:
    response = await client.get(
        f"{YANDEX_API_BASE}/resources",
        params={"path": watch_path, "limit": 200},
    )
    response.raise_for_status()
    items = response.json().get("_embedded", {}).get("items", [])
    return select_pending_files(items)


async def _download_file(client: httpx.AsyncClient, file_path: str) -> bytes:
    link_response = await client.get(
        f"{YANDEX_API_BASE}/resources/download", params={"path": file_path}
    )
    link_response.raise_for_status()
    href = link_response.json()["href"]

    # The download href is a pre-signed, self-contained URL - fetch it with a
    # bare client (no Authorization header needed or expected here).
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as plain_client:
        content_response = await plain_client.get(href)
        content_response.raise_for_status()
        return content_response.content


async def _move_to_processed(client: httpx.AsyncClient, watch_path: str, file_path: str) -> None:
    destination = _processed_path(watch_path, file_path)
    response = await client.post(
        f"{YANDEX_API_BASE}/resources/move",
        params={"from": file_path, "path": destination, "overwrite": "true"},
    )
    response.raise_for_status()


async def _import_one_file(client: httpx.AsyncClient, watch_path: str, item: dict) -> None:
    file_path = item["path"]
    file_name = item.get("name", file_path)

    try:
        raw_bytes = await _download_file(client, file_path)
        payload = ImportWorkOrdersRequest.model_validate_json(raw_bytes)
    except (httpx.HTTPError, ValidationError, json.JSONDecodeError) as exc:
        # Leave the file in place - a malformed/unreachable file should not
        # silently disappear; it stays visible for manual investigation and
        # is retried next poll (harmless if the cause was transient).
        logger.error("yandex_relay_file_unreadable", file=file_name, error=str(exc))
        return

    db = SessionLocal()
    try:
        batch = process_work_order_import(db, payload)
        logger.info(
            "yandex_relay_import_completed",
            file=file_name,
            batch_id=batch.batch_id,
            inserted=batch.records_inserted,
            updated=batch.records_updated,
        )
    except ImportProcessingError as exc:
        logger.error("yandex_relay_import_failed", file=file_name, error=str(exc))
        return
    finally:
        db.close()

    try:
        await _move_to_processed(client, watch_path, file_path)
    except httpx.HTTPError as exc:
        # Import already succeeded and is idempotent, so worst case on a
        # failed move is the same file gets imported again next poll - not
        # data loss, just wasted work. Log and move on.
        logger.warning("yandex_relay_move_failed", file=file_name, error=str(exc))


async def poll_once() -> None:
    """Run a single check-and-import pass over the watched Yandex.Disk folder."""
    settings = get_settings()
    if not settings.yandex_disk_oauth_token:
        logger.error("yandex_relay_missing_token")
        return

    headers = {"Authorization": f"OAuth {settings.yandex_disk_oauth_token}"}
    async with httpx.AsyncClient(headers=headers, timeout=REQUEST_TIMEOUT_SECONDS) as client:
        await _ensure_watch_folders_exist(client, settings.yandex_disk_watch_path)
        try:
            files = await _list_files(client, settings.yandex_disk_watch_path)
        except httpx.HTTPError as exc:
            logger.error("yandex_relay_list_failed", error=str(exc))
            return

        for item in files:
            await _import_one_file(client, settings.yandex_disk_watch_path, item)


async def run_relay_loop() -> None:
    """Poll forever at the configured interval. Intended to run as a background
    asyncio task started from the FastAPI startup event - see app/main.py.
    """
    settings = get_settings()
    logger.info(
        "yandex_relay_started",
        watch_path=settings.yandex_disk_watch_path,
        interval_seconds=settings.yandex_poll_interval_seconds,
    )
    while True:
        try:
            await poll_once()
        except Exception as exc:  # noqa: BLE001 - never let the poll loop die
            logger.error("yandex_relay_unexpected_error", error=str(exc))
        await asyncio.sleep(settings.yandex_poll_interval_seconds)
