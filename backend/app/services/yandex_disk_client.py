"""Sync Yandex.Disk client for the call-recording archive (see
services/call_recording_service.py) - not to be confused with
services/yandex_relay.py, which is an async *inbound* watcher (1C export
files arriving on Disk) using httpx.AsyncClient. This module is the
*outbound* direction (uploading recordings/transcripts this backend
produces) and is synchronous, matching services/zeon_client.py's style,
since it's driven from the same synchronous export pipeline.

Ported from Zeon_AI/zeon_to_yadisk.py's `YandexDisk` class (same API
shape/behavior - ensure_path/list_files/download/upload), reshaped onto
httpx instead of `requests`.
"""

from __future__ import annotations

import httpx

API_BASE = "https://cloud-api.yandex.net/v1/disk"
REQUEST_TIMEOUT_SECONDS = 60.0
DOWNLOAD_TIMEOUT_SECONDS = 180.0


class YaDiskError(Exception):
    """Raised on any non-2xx Yandex.Disk API response (except the specific
    404/409 cases each method treats as meaningful, not an error)."""


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"OAuth {token}", "Accept": "application/json"}


def _error(response: httpx.Response, what: str) -> YaDiskError:
    try:
        info = response.json()
        detail = f"{info.get('error')}: {info.get('message') or info.get('description')}"
    except ValueError:
        detail = response.text[:200]
    return YaDiskError(f"{what}: HTTP {response.status_code} {detail}")


def ensure_folder(client: httpx.Client, token: str, path: str) -> bool:
    """Creates one folder. Returns True if created, False if it already existed."""
    response = client.put(f"{API_BASE}/resources", params={"path": path}, headers=_headers(token))
    if response.status_code == 201:
        return True
    if response.status_code == 409:
        try:
            code = response.json().get("error")
        except ValueError:
            code = None
        if code == "DiskPathDoesntExistsError":
            raise YaDiskError(f"Cannot create {path}: parent folder doesn't exist")
        return False
    raise _error(response, f"create folder {path}")


def ensure_path(client: httpx.Client, token: str, base: str, *parts: str) -> bool:
    """Creates base/part1/part2/... level by level (base must already
    exist). Returns True if the last segment was newly created."""
    created = False
    path = base
    for part in parts:
        path = f"{path}/{part}"
        created = ensure_folder(client, token, path)
    return created


def list_files(client: httpx.Client, token: str, folder: str) -> dict[str, int]:
    """{name: size} for a folder's contents; empty dict if the folder
    doesn't exist (a fresh day - not an error)."""
    files: dict[str, int] = {}
    offset, limit = 0, 1000
    while True:
        response = client.get(
            f"{API_BASE}/resources",
            params={
                "path": folder,
                "limit": limit,
                "offset": offset,
                "fields": "_embedded.items.name,_embedded.items.size,_embedded.total",
            },
            headers=_headers(token),
        )
        if response.status_code == 404:
            return files
        if response.status_code != 200:
            raise _error(response, f"list folder {folder}")
        embedded = response.json().get("_embedded") or {}
        items = embedded.get("items") or []
        files.update((item["name"], int(item.get("size") or 0)) for item in items if "name" in item)
        offset += len(items)
        if not items or offset >= int(embedded.get("total") or 0):
            return files


def list_names(client: httpx.Client, token: str, folder: str) -> set[str]:
    return set(list_files(client, token, folder))


def download(client: httpx.Client, token: str, path: str) -> bytes:
    response = client.get(
        f"{API_BASE}/resources/download", params={"path": path}, headers=_headers(token)
    )
    if response.status_code != 200:
        raise _error(response, f"get download link for {path}")
    href = response.json()["href"]
    # The download href is a pre-signed, self-contained URL - no auth header.
    with httpx.Client(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as plain_client:
        content_response = plain_client.get(href)
        if content_response.status_code != 200:
            raise _error(content_response, f"download {path}")
        return content_response.content


def upload(
    client: httpx.Client, token: str, path: str, data: bytes, overwrite: bool = False
) -> bool:
    """Uploads a file. Without overwrite: True if uploaded, False if a file
    was already there (the idempotency check the export pipeline relies
    on - see call_recording_service)."""
    response = client.get(
        f"{API_BASE}/resources/upload",
        params={"path": path, "overwrite": "true" if overwrite else "false"},
        headers=_headers(token),
    )
    if response.status_code == 409:
        return False
    if response.status_code != 200:
        raise _error(response, f"get upload link for {path}")

    href = response.json()["href"]
    put_response = client.put(href, content=data, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    if put_response.status_code not in (201, 202):
        raise _error(put_response, f"upload {path}")
    return True


def new_client() -> httpx.Client:
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
