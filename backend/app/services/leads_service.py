"""Website leads (pan-motors.ru's quiz/consultation/installment forms) -
intake, listing, and the "still needs a callback" resolution logic that
feeds the Planner's envelope badge (see components/planner/LeadsBadge.tsx).

Resolution rule (confirmed product decision, 2026-09-29): unlike the
telephony missed-calls badge (either direction resolves a miss), a lead is
only "handled" by a real **outbound** call to it that was actually answered
(>= MIN_REAL_TALK_SEC of talk time) - a lead is an inbound inquiry that
needs *our* staff to call back, so an inbound call to the same number
proves nothing about whether anyone followed up on it. A lead past
`stale_after_days` with no such call stops counting as "open" (badge/count)
but is never deleted - it just reads as "stale" on the full Заявки page
instead of "new", so nothing quietly vanishes the way a missed call does.
"""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.call_record import CALL_TYPE_OUT, CallRecord
from app.models.leads_settings import LeadsSettings
from app.models.website_lead import (
    SOURCE_CONSULTATION,
    SOURCE_INSTALLMENT,
    SOURCE_OTHER,
    SOURCE_QUIZ_BODY,
    SOURCE_QUIZ_MECHANICAL,
    WebsiteLead,
)
from app.services.telephony_stats_service import MIN_REAL_TALK_SEC

SETTINGS_ID = 1

_FORM_NAME_SOURCES = {
    "Получите быстрый ответ по цене и времени записи": SOURCE_QUIZ_MECHANICAL,
    "Получить консультацию": SOURCE_CONSULTATION,
    "Рассрочка": SOURCE_INSTALLMENT,
}

LeadStatus = Literal["open", "resolved", "stale"]


# ---- Настройки --------------------------------------------------------


def get_leads_settings(db: Session) -> LeadsSettings:
    settings = db.get(LeadsSettings, SETTINGS_ID)
    if settings is None:
        settings = LeadsSettings(id=SETTINGS_ID)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_leads_settings(db: Session, *, enabled: bool, stale_after_days: int) -> LeadsSettings:
    settings = get_leads_settings(db)
    settings.enabled = enabled
    settings.stale_after_days = stale_after_days
    db.commit()
    db.refresh(settings)
    return settings


def regenerate_intake_token(db: Session) -> LeadsSettings:
    settings = get_leads_settings(db)
    settings.intake_token = secrets.token_urlsafe(32)
    db.commit()
    db.refresh(settings)
    return settings


def verify_intake_token(db: Session, token: str | None) -> bool:
    settings = get_leads_settings(db)
    if not settings.enabled or not settings.intake_token or not token:
        return False
    return secrets.compare_digest(token, settings.intake_token)


# ---- Приём заявок -------------------------------------------------------


def _normalize_phone(value: Any) -> str:
    """Last 10 digits - same convention as telephony_calls.client (see
    services/zeon_client.py's _norm_phone), so a lead can be matched
    against a real outbound call to the same number."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else digits


def _classify_source(payload: dict[str, Any]) -> str:
    """The кузовной quiz sends no `form_name` at all (only the site's other
    3 form types do) - it's identified by having any `quiz_damage[...]`
    key instead. See the 2026-09-29 product brief for the full field
    contract this was reverse-engineered from."""
    if any(key.startswith("quiz_damage") for key in payload):
        return SOURCE_QUIZ_BODY
    form_name = str(payload.get("form_name") or "").strip()
    return _FORM_NAME_SOURCES.get(form_name, SOURCE_OTHER)


def _extract_photos(payload: dict[str, Any]) -> list[str] | None:
    """`files` is a `;`-separated list of filenames, `folder` the numeric
    upload folder they were dropped into (site's Dropzone uploader posts to
    /tmp_files/upload.php?folder=<folder> separately, before the form
    itself is submitted) - see product brief section 5."""
    files = str(payload.get("files") or "").strip()
    folder = str(payload.get("folder") or "").strip()
    if not files or not folder:
        return None
    names = [name for name in files.split(";") if name.strip()]
    if not names:
        return None
    return [f"https://pan-motors.ru/tmp_files/{folder}/{name}" for name in names]


class LeadRejected(Exception):
    """A submitted lead has no usable phone number - see create_lead."""


def create_lead(db: Session, payload: dict[str, Any]) -> WebsiteLead:
    phone = _normalize_phone(payload.get("user_phone"))
    if len(phone) < 10:
        raise LeadRejected("user_phone is missing or too short")

    # Single-use, ~2500-char reCAPTCHA token - useless once verified
    # client-side/by the site's own init.php, not worth storing.
    stored_payload = {k: v for k, v in payload.items() if k != "recaptcha_response"}

    lead = WebsiteLead(
        id=uuid.uuid4(),
        source=_classify_source(payload),
        phone=phone,
        name=(str(payload.get("user_name")).strip() or None) if payload.get("user_name") else None,
        photos=_extract_photos(payload),
        raw_payload=stored_payload,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


# ---- Список / статус -----------------------------------------------------


@dataclass
class LeadWithStatus:
    lead: WebsiteLead
    status: LeadStatus


def _resolving_calls_by_phone(db: Session) -> dict[str, list[datetime]]:
    """Every real (>=5s, answered) outbound call, grouped by client phone -
    fetched once and matched in Python rather than one query per lead."""
    rows = db.execute(
        select(CallRecord.client, CallRecord.occurred_at).where(
            CallRecord.call_type == CALL_TYPE_OUT,
            CallRecord.talk_sec >= MIN_REAL_TALK_SEC,
            CallRecord.client.is_not(None),
        )
    ).all()
    by_phone: dict[str, list[datetime]] = {}
    for client, occurred_at in rows:
        by_phone.setdefault(client, []).append(occurred_at)
    return by_phone


def _status_for(
    lead: WebsiteLead, resolving_calls: list[datetime], *, stale_cutoff: datetime
) -> LeadStatus:
    if any(t > lead.created_at for t in resolving_calls):
        return "resolved"
    return "open" if lead.created_at >= stale_cutoff else "stale"


def list_leads(db: Session, *, now: datetime | None = None) -> list[LeadWithStatus]:
    """Every lead ever received, newest first, each with its computed
    status - feeds the full "Заявки" page."""
    now = now or datetime.now(UTC)
    settings = get_leads_settings(db)
    stale_cutoff = now - timedelta(days=settings.stale_after_days)

    leads = list(db.scalars(select(WebsiteLead).order_by(WebsiteLead.created_at.desc())))
    resolving = _resolving_calls_by_phone(db)
    return [
        LeadWithStatus(
            lead=lead,
            status=_status_for(lead, resolving.get(lead.phone, []), stale_cutoff=stale_cutoff),
        )
        for lead in leads
    ]


def get_open_leads(db: Session, *, now: datetime | None = None) -> list[WebsiteLead]:
    """Leads that still need a callback - not yet reached by a real
    outbound call, and not yet past stale_after_days - feeds the Planner's
    envelope badge. Newest first."""
    return [item.lead for item in list_leads(db, now=now) if item.status == "open"]
