"""Website leads (pan-motors.ru's forms) - intake from the site, listing
and settings for the app itself.

Unlike every other router in this API, `/intake` is deliberately NOT behind
`verify_api_token` (the app's own shared bearer token) - it's called by a
client-run WordPress site we don't administer, authenticated instead
against its own separate, rotatable `LeadsSettings.intake_token` (see
services/leads_service.py's module docstring for why). Every other route
here still uses the normal `verify_api_token`, same as the rest of the app.
"""

import mimetypes
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.models.website_lead import WebsiteLead
from app.schemas.leads import (
    LeadsIntakeTokenOut,
    LeadsSettingsOut,
    LeadsSettingsUpdate,
    OpenLeadsResponse,
    WebsiteLeadOut,
    WebsiteLeadsResponse,
)
from app.services import (
    lead_photos_service,
    leads_service,
    telephony_settings_service,
    yandex_disk_client,
)
from app.services.leads_service import LeadRejected
from app.services.yandex_disk_client import YaDiskError

router = APIRouter(prefix="/leads", tags=["leads"])


def _settings_out(settings) -> LeadsSettingsOut:  # noqa: ANN001
    return LeadsSettingsOut(
        enabled=settings.enabled,
        stale_after_days=settings.stale_after_days,
        has_intake_token=bool(settings.intake_token),
    )


def _lead_out(item: leads_service.LeadWithStatus) -> WebsiteLeadOut:
    lead = item.lead
    return WebsiteLeadOut(
        id=lead.id,
        source=lead.source,
        phone=lead.phone,
        name=lead.name,
        photos=lead.photos,
        raw_payload=lead.raw_payload,
        created_at=lead.created_at,
        status=item.status,
        matched_work_order_id=item.matched_work_order_id,
        matched_work_order_number=item.matched_work_order_number,
    )


# ---- Приём с сайта (отдельная авторизация) --------------------------------


@router.post("/intake", status_code=status.HTTP_201_CREATED)
def intake_lead(
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """A plain `def` endpoint on purpose (unlike most of this router, which
    doesn't need to care either way) - FastAPI then runs this on Starlette's
    own request threadpool, same as every other synchronous route in this
    app (see db/session.py's own docstring). That pool is separate from the
    raw asyncio default executor the 4 always-on background relays (see
    app/main.py's lifespan) share via their own `asyncio.to_thread` calls -
    this endpoint used to `await asyncio.to_thread(...)` here too (to avoid
    blocking the event loop while archiving photos, see lead_photos_service),
    which put it in direct contention for that SAME shared executor: a
    relay cycle mid-SpeechKit-poll (services/call_transcription_service._
    transcribe's own sleep loop, now longer since the 2026-10-05 adapt_
    transcript/full-model changes) occupies one of only
    min(32, cpu_count+4) threads for minutes at a time, so an incoming
    lead could queue behind it even with zero photos of its own to
    archive - confirmed as the cause of intermittent 10-15s site-side
    hangs reported 2026-10-06 (occurred on photo-less submissions too,
    which ruled out archive_photos' own per-photo network calls as the
    cause)."""
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    if not leads_service.verify_intake_token(db, token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid intake token")

    try:
        lead = leads_service.create_lead(db, payload)
    except LeadRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return {"id": str(lead.id)}


# ---- Просмотр / настройки (обычная авторизация) ---------------------------


@router.get("", response_model=WebsiteLeadsResponse, dependencies=[Depends(verify_api_token)])
def list_leads(db: Session = Depends(get_db)) -> WebsiteLeadsResponse:
    items = leads_service.list_leads(db)
    return WebsiteLeadsResponse(leads=[_lead_out(item) for item in items])


@router.get("/open", response_model=OpenLeadsResponse, dependencies=[Depends(verify_api_token)])
def open_leads(db: Session = Depends(get_db)) -> OpenLeadsResponse:
    items = [item for item in leads_service.list_leads(db) if item.status == "open"]
    leads = [_lead_out(item) for item in items]
    return OpenLeadsResponse(count=len(leads), leads=leads)


@router.get("/{lead_id}/photos/{filename}", dependencies=[Depends(verify_api_token)])
def get_lead_photo(lead_id: uuid.UUID, filename: str, db: Session = Depends(get_db)) -> Response:
    """Streams one of this lead's photos from our own Yandex.Disk archive
    (see services/lead_photos_service.py) - the browser never talks to
    pan-motors.ru or Yandex.Disk directly."""
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")

    lead = db.get(WebsiteLead, lead_id)
    if lead is None or not lead.photos:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead or photo not found")

    settings = telephony_settings_service.get_telephony_settings(db)
    if not settings.yandex_disk_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Photo storage not configured"
        )

    path = lead_photos_service.photo_disk_path(lead_id, filename)
    try:
        with yandex_disk_client.new_client() as client:
            data = yandex_disk_client.download(client, settings.yandex_disk_token, path)
    except YaDiskError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found"
        ) from exc

    media_type, _ = mimetypes.guess_type(filename)
    return Response(content=data, media_type=media_type or "application/octet-stream")


@router.get("/settings", response_model=LeadsSettingsOut, dependencies=[Depends(verify_api_token)])
def read_leads_settings(db: Session = Depends(get_db)) -> LeadsSettingsOut:
    return _settings_out(leads_service.get_leads_settings(db))


@router.put("/settings", response_model=LeadsSettingsOut, dependencies=[Depends(verify_api_token)])
def write_leads_settings(
    payload: LeadsSettingsUpdate, db: Session = Depends(get_db)
) -> LeadsSettingsOut:
    settings = leads_service.update_leads_settings(
        db, enabled=payload.enabled, stale_after_days=payload.stale_after_days
    )
    return _settings_out(settings)


@router.post(
    "/settings/regenerate-token",
    response_model=LeadsIntakeTokenOut,
    dependencies=[Depends(verify_api_token)],
)
def regenerate_intake_token(db: Session = Depends(get_db)) -> LeadsIntakeTokenOut:
    settings = leads_service.regenerate_intake_token(db)
    return LeadsIntakeTokenOut(intake_token=settings.intake_token)
