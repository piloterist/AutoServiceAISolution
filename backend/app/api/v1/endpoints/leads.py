"""Website leads (pan-motors.ru's forms) - intake from the site, listing
and settings for the app itself.

Unlike every other router in this API, `/intake` is deliberately NOT behind
`verify_api_token` (the app's own shared bearer token) - it's called by a
client-run WordPress site we don't administer, authenticated instead
against its own separate, rotatable `LeadsSettings.intake_token` (see
services/leads_service.py's module docstring for why). Every other route
here still uses the normal `verify_api_token`, same as the rest of the app.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import verify_api_token
from app.db.session import get_db
from app.schemas.leads import (
    LeadsIntakeTokenOut,
    LeadsSettingsOut,
    LeadsSettingsUpdate,
    OpenLeadsResponse,
    WebsiteLeadOut,
    WebsiteLeadsResponse,
)
from app.services import leads_service
from app.services.leads_service import LeadRejected

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
    )


# ---- Приём с сайта (отдельная авторизация) --------------------------------


@router.post("/intake", status_code=status.HTTP_201_CREATED)
async def intake_lead(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    if not leads_service.verify_intake_token(db, token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid intake token")

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Expected a JSON object"
        )

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
