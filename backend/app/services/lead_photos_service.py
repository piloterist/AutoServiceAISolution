"""Downloads a lead's photos from wherever the site's own form posted them
(pan-motors.ru's own `/tmp_files/<folder>/<file>` upload scratch folder -
see leads_service._extract_photos) and archives them on Yandex.Disk, so
they survive that folder being cleaned up on the site's own side (confirmed
happening live, 2026-10-02 - the operator found a lead whose photo link
already 404s). Reuses the same Yandex.Disk account already configured for
the telephony call-recording archive (see models/telephony_settings.py's
yandex_disk_token) - a separate client-site integration, but there's only
one Yandex.Disk account in this whole system, and a second settings form
asking for the same OAuth token would just be a second place for it to go
stale.

Best-effort only: this runs inline as part of accepting the lead (see
services/leads_service.create_lead), so a dead link, a slow site, or
Yandex.Disk being briefly unavailable must never reject the lead itself -
a photo that can't be fetched/archived is just dropped (logged, not
raised), the same "swallow and move on" principle the site's own PHP
relay already applies to sending us the lead in the first place (see
Pan-Motors_web.md).
"""

from __future__ import annotations

import uuid
from urllib.parse import urlparse

import httpx
import structlog

from app.services import yandex_disk_client
from app.services.yandex_disk_client import YaDiskError

logger = structlog.get_logger(__name__)

DISK_BASE_PATH = "disk:/Leads"
FETCH_TIMEOUT_SECONDS = 15.0


def _filename_from_url(url: str) -> str:
    return urlparse(url).path.rsplit("/", 1)[-1] or "photo.jpg"


def photo_disk_path(lead_id: uuid.UUID, filename: str) -> str:
    return f"{DISK_BASE_PATH}/{lead_id}/{filename}"


def archive_photos(
    photo_urls: list[str], lead_id: uuid.UUID, yandex_disk_token: str | None
) -> list[str]:
    """Downloads each of the site's own (likely short-lived) photo URLs and
    re-uploads it to our own Yandex.Disk folder, returning the matching
    list of OUR OWN serving paths (see endpoints/leads.py's get_lead_photo)
    - those paths are what actually get stored on WebsiteLead.photos, never
    the original pan-motors.ru URLs. A photo that fails to download/upload
    is silently dropped rather than losing the whole lead over one bad
    link; if the token itself isn't configured, every photo is dropped
    (nothing to archive to) - the lead itself is still created either way,
    see create_lead."""
    if not photo_urls or not yandex_disk_token:
        return []

    archived: list[str] = []
    try:
        with (
            httpx.Client(timeout=FETCH_TIMEOUT_SECONDS) as fetch_client,
            yandex_disk_client.new_client() as disk_client,
        ):
            folder_ready = False
            for url in photo_urls:
                filename = _filename_from_url(url)
                try:
                    response = fetch_client.get(url, follow_redirects=True)
                except httpx.HTTPError as exc:
                    logger.warning("lead_photo_fetch_failed", url=url, error=str(exc))
                    continue

                raw_content_type = response.headers.get("content-type", "")
                content_type = raw_content_type.split(";")[0].strip().lower()
                # application/octet-stream allowed too - same leniency as
                # zeon_client.download_audio for a server that doesn't
                # bother guessing a real image/* type for a static file.
                image_exts = ("jpeg", "jpg", "png", "webp", "gif", "heic", "heif")
                allowed_types = (
                    "application/octet-stream",
                    *(f"image/{ext}" for ext in image_exts),
                )
                if response.status_code != 200 or content_type not in allowed_types:
                    logger.warning(
                        "lead_photo_fetch_bad_response",
                        url=url,
                        status=response.status_code,
                        content_type=content_type,
                    )
                    continue

                if not folder_ready:
                    try:
                        yandex_disk_client.ensure_path(
                            disk_client, yandex_disk_token, DISK_BASE_PATH, str(lead_id)
                        )
                    except YaDiskError as exc:
                        logger.error(
                            "lead_photo_folder_failed", lead_id=str(lead_id), error=str(exc)
                        )
                        return archived
                    folder_ready = True

                try:
                    yandex_disk_client.upload(
                        disk_client,
                        yandex_disk_token,
                        photo_disk_path(lead_id, filename),
                        response.content,
                    )
                except YaDiskError as exc:
                    logger.error("lead_photo_upload_failed", url=url, error=str(exc))
                    continue

                archived.append(f"/api/leads/{lead_id}/photos/{filename}")
    except Exception as exc:  # noqa: BLE001 - a photo-archive bug must never reject the lead itself
        logger.error("lead_photo_archive_unexpected_error", lead_id=str(lead_id), error=str(exc))

    return archived
