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
import re
import uuid
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.models.website_lead import WebsiteLead
from app.schemas.leads import (
    LeadCallOut,
    LeadCallsResponse,
    LeadsIntakeTokenOut,
    LeadsSettingsOut,
    LeadsSettingsUpdate,
    OpenLeadsResponse,
    WebsiteLeadOut,
    WebsiteLeadsResponse,
)
from app.services import (
    call_recording_service,
    lead_photos_service,
    leads_service,
    telephony_settings_service,
    yandex_disk_client,
)
from app.services.lead_intake_normalizer import normalize_site_fields
from app.services.leads_service import LeadRejected
from app.services.yandex_disk_client import YaDiskError

router = APIRouter(prefix="/leads", tags=["leads"])


def _settings_out(settings) -> LeadsSettingsOut:  # noqa: ANN001
    return LeadsSettingsOut(
        enabled=settings.enabled,
        stale_after_days=settings.stale_after_days,
        has_intake_token=bool(settings.intake_token),
    )


def _lead_call_out(row) -> LeadCallOut:  # noqa: ANN001 - app.models.call_record.CallRecord
    return LeadCallOut(
        call_id=row.id,
        occurred_at=row.occurred_at,
        call_type=row.call_type,
        operator=row.operator,
        answered=row.answered,
        wait_sec=row.wait_sec,
        talk_sec=row.talk_sec,
        transcript_status=row.transcript_status,
        transcript_text=row.transcript_text,
        transcript_text_raw=row.transcript_text_raw,
        topic_tag=row.topic_tag,
        quality_score=row.quality_score,
        quality_review=row.quality_review,
        has_recording=call_recording_service.recording_link(row) is not None,
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
        request_meta=lead.request_meta,
        site=leads_service.site_from_meta(lead.request_meta),
        created_at=lead.created_at,
        status=item.status,
        matched_work_order_id=item.matched_work_order_id,
        matched_work_order_number=item.matched_work_order_number,
    )


# ---- Приём с сайта (отдельная авторизация) --------------------------------


MAX_UPLOADED_PHOTOS = 10
MAX_PHOTO_BYTES = 12 * 1024 * 1024


def _safe_filename(name: str, index: int) -> str:
    """Имя файла из формы - только безопасные символы (оно попадает в путь на Яндекс.Диске и в
    адрес фото), без каталогов."""
    base = re.split(r"[\/]", name or "")[-1].strip()
    cleaned = re.sub(r"[^\w.\- ]+", "_", base, flags=re.UNICODE).strip(" .")
    return cleaned or f"photo-{index + 1}.jpg"


async def _read_intake_body(request: Request) -> tuple[dict[str, Any], list[tuple[str, bytes]]]:
    """Тело заявки: JSON (наш формат) или форма (urlencoded / multipart, как шлёт сайт на Webflow).
    Из формы файлы (file[], file, любые части с файлом) отдаём отдельно, пустые поля без файла
    пропускаем."""
    content_type = request.headers.get("content-type", "").lower()
    if "json" in content_type or not content_type:
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Body is not valid JSON"
            ) from exc
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Body must be an object"
            )
        return body, []

    form = await request.form()
    fields: dict[str, Any] = {}
    photos: list[tuple[str, bytes]] = []
    for key in form.keys():
        values = form.getlist(key)
        files = [v for v in values if isinstance(v, UploadFile)]
        if files:
            for upload in files:
                if not upload.filename or len(photos) >= MAX_UPLOADED_PHOTOS:
                    continue
                content = await upload.read()
                if content and len(content) <= MAX_PHOTO_BYTES:
                    photos.append((_safe_filename(upload.filename, len(photos)), content))
            continue
        fields[key] = values[0] if len(values) == 1 else list(values)
    return fields, photos


@router.post("/intake", status_code=status.HTTP_201_CREATED)
async def intake_lead(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Приём заявки с сайта: JSON (формат WordPress-сайта) или обычная форма / multipart (сайты
    на Webflow и др.); имена полей приводятся к нашим (lead_intake_normalizer), фото могут
    прийти файлами прямо в запросе.

    Блокирующую работу (база, Яндекс.Диск) выполняем в `run_in_threadpool`, то есть в том же пуле
    потоков Starlette, где идут обычные `def`-эндпоинты, а не в общем executor asyncio: его
    занимают фоновые циклы расшифровки звонков (см. прежнее описание этого эндпоинта и
    db/session.py), заявка с сайта не должна ждать за ними (10-15 с зависаний формы 2026-10-06)."""
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    if not await run_in_threadpool(leads_service.verify_intake_token, db, token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid intake token")

    raw, uploaded = await _read_intake_body(request)
    payload = normalize_site_fields(raw)
    meta = leads_service.request_meta_from(
        request.headers, request.client.host if request.client else None
    )
    try:
        lead = await run_in_threadpool(leads_service.create_lead, db, payload, meta, uploaded)
    except LeadRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Photo links (copies kept by the site) are downloaded after the answer is sent.
    photo_urls = leads_service.photo_urls_to_archive(payload)
    if photo_urls:
        background_tasks.add_task(
            leads_service.archive_lead_photos_from_urls, db.get_bind(), lead.id, photo_urls
        )

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


@router.get(
    "/{lead_id}/calls", response_model=LeadCallsResponse, dependencies=[Depends(verify_api_token)]
)
def lead_calls(lead_id: uuid.UUID, db: Session = Depends(get_db)) -> LeadCallsResponse:
    """Expanded lead detail card's call-history section (product ask,
    2026-10-21) - see services/leads_service.list_calls_for_lead."""
    lead = db.get(WebsiteLead, lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    rows = leads_service.list_calls_for_lead(db, lead)
    return LeadCallsResponse(calls=[_lead_call_out(row) for row in rows])


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
