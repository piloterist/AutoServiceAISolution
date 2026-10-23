"""Website leads (pan-motors.ru's quiz/consultation/installment forms) -
intake, listing, and the "still needs a callback" resolution logic that
feeds the Planner's envelope badge (see components/planner/LeadsBadge.tsx).

Resolution rule (revised 2026-10-21, see below for the superseded version):
a lead is "handled" by any real, answered call to/from its phone number -
either direction, same as the telephony missed-calls badge - with at least
MIN_REAL_TALK_SEC of talk time. A lead past `stale_after_days` with no such
call stops counting as "open" (badge/count) but is never deleted - it just
reads as "stale" on the full Заявки page instead of "new", so nothing
quietly vanishes the way a missed call does.

Originally (confirmed product decision, 2026-09-29) only an **outbound**
call counted - the reasoning being that a lead is an inbound inquiry that
needs *our* staff to call back, so an inbound call proves nothing about
whether anyone followed up. Dropped after a real counter-example: a lead
left open "Просрочена" despite the client themselves calling back and
having a full, substantive 260s conversation with staff that fully
addressed the lead's request - an inbound call CAN prove follow-up
happened, same as an outbound one, provided it's a real conversation and
not just noise (which MIN_REAL_TALK_SEC already screens for, regardless of
direction).
"""

from __future__ import annotations

import base64
import binascii
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.call_record import CallRecord
from app.models.leads_settings import LeadsSettings
from app.models.website_lead import (
    SOURCE_CONSULTATION,
    SOURCE_INSTALLMENT,
    SOURCE_OTHER,
    SOURCE_QUIZ_BODY,
    SOURCE_QUIZ_MECHANICAL,
    WebsiteLead,
)
from app.models.work_order import WorkOrder
from app.services import lead_photos_service, telephony_settings_service
from app.services.telephony_stats_service import MIN_REAL_TALK_SEC

logger = structlog.get_logger(__name__)

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
    against a real call to the same number."""
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


def _extract_inline_photos(payload: dict[str, Any]) -> list[tuple[str, bytes]]:
    """`photos_data`: `[{"filename": ..., "content_base64": ...}, ...]` -
    the site reading its own tmp_files/<folder>/<name> scratch files itself
    and sending the bytes inline, instead of just the filenames/folder for
    us to fetch separately (see Pan-Motors_web.md for the matching PHP).

    Added 2026-10-21 after confirming live that the old fetch-by-URL path
    (_extract_photos/lead_photos_service.archive_photos) essentially always
    loses the race against the site's own tmp_files cleanup: disk:/Leads
    existed and was reachable, but had archived zero photos across weeks of
    real leads with files attached - every fetch was landing on an
    already-404'd link, the very same file the site's own Telegram-send
    code reads successfully moments earlier in the same request. Reading
    the bytes at that same moment (instead of a second, later, separate
    HTTP round trip) is the actual fix; see create_lead for how this is
    preferred over the old path.

    A malformed entry is skipped (logged), never raised - same "a lead must
    never be rejected over a bad photo" principle as archive_photos
    itself."""
    entries = payload.get("photos_data")
    if not isinstance(entries, list):
        return []

    photos: list[tuple[str, bytes]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        filename = str(entry.get("filename") or "").strip()
        content_b64 = entry.get("content_base64")
        if not filename or not isinstance(content_b64, str):
            continue
        try:
            content = base64.b64decode(content_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            logger.warning("lead_photo_inline_decode_failed", filename=filename, error=str(exc))
            continue
        if not content:
            continue
        photos.append((filename, content))
    return photos


class LeadRejected(Exception):
    """A submitted lead has no usable phone number - see create_lead."""


def create_lead(db: Session, payload: dict[str, Any]) -> WebsiteLead:
    phone = _normalize_phone(payload.get("user_phone"))
    if len(phone) < 10:
        raise LeadRejected("user_phone is missing or too short")

    # Single-use, ~2500-char reCAPTCHA token - useless once verified
    # client-side/by the site's own init.php, not worth storing. photos_data
    # is excluded too - it's base64 image bytes, already archived to
    # Yandex.Disk below, so keeping a second copy in raw_payload would just
    # bloat this JSONB column for nothing.
    stored_payload = {
        k: v for k, v in payload.items() if k not in ("recaptcha_response", "photos_data")
    }

    # The site's own /tmp_files/<folder>/<name> links are a short-lived
    # upload scratch area, not durable storage - archive onto our own
    # Yandex.Disk (see lead_photos_service) and store OUR serving paths
    # instead, so the photo survives that folder being cleaned up.
    lead_id = uuid.uuid4()
    disk_token = telephony_settings_service.get_telephony_settings(db).yandex_disk_token
    inline_photos = _extract_inline_photos(payload)
    if inline_photos:
        photos = lead_photos_service.archive_photo_bytes(inline_photos, lead_id, disk_token) or None
    else:
        # Fallback for a payload that doesn't send photos_data yet (or
        # never will, e.g. an older/unrelated caller) - see this function's
        # own docstring on why this path alone isn't reliable any more.
        source_photo_urls = _extract_photos(payload) or []
        photos = lead_photos_service.archive_photos(source_photo_urls, lead_id, disk_token) or None

    lead = WebsiteLead(
        id=lead_id,
        source=_classify_source(payload),
        phone=phone,
        name=(str(payload.get("user_name")).strip() or None) if payload.get("user_name") else None,
        photos=photos,
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
    # The first work order (ЗН) created for this same phone number *after*
    # this lead came in (see _match_work_order) - computed live on every
    # read, same as `status` above, not stored: a work order imported from
    # 1C days after the lead still arrived still just as "new" is matched
    # the very next time this page loads, no separate relay/backfill job
    # needed (product ask, 2026-10-04). None if nothing has matched yet, or
    # the only work orders on this phone predate the lead (an old,
    # unrelated visit - must not be shown as if it came from this lead).
    matched_work_order_id: uuid.UUID | None = None
    matched_work_order_number: str | None = None


def _resolving_calls_by_phone(db: Session) -> dict[str, list[datetime]]:
    """Every real (>=5s, answered) call, either direction, grouped by
    client phone - fetched once and matched in Python rather than one
    query per lead. See this module's own docstring for why direction
    stopped mattering here."""
    rows = db.execute(
        select(CallRecord.client, CallRecord.occurred_at).where(
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


def _work_orders_by_phone(db: Session) -> dict[str, list[tuple[datetime, uuid.UUID, str]]]:
    """Every work order with a phone at all, grouped by that phone
    (normalized the same way WebsiteLead.phone already is), each list
    sorted oldest-created-first - fetched once and matched in Python, same
    shape as _resolving_calls_by_phone above. WorkOrder.phone is raw 1C
    passthrough (see models/work_order.py), hence the normalization here
    rather than a direct column comparison."""
    rows = db.execute(
        select(
            WorkOrder.phone,
            WorkOrder.created_date,
            WorkOrder.created_at,
            WorkOrder.id,
            WorkOrder.external_number,
        ).where(WorkOrder.phone.is_not(None))
    ).all()
    by_phone: dict[str, list[tuple[datetime, uuid.UUID, str]]] = {}
    for phone, created_date, row_created_at, work_order_id, external_number in rows:
        # The real creation date (ДатаСоздания, filled for every order) -
        # not created_at, which is only when our import first saw the row
        # (product ask, 2026-10-23: for the history loaded in one go that is
        # the import day, so an old order looked "created after" a lead).
        created_at = created_date or row_created_at
        normalized = _normalize_phone(phone)
        if len(normalized) < 10:
            continue
        by_phone.setdefault(normalized, []).append((created_at, work_order_id, external_number))
    for entries in by_phone.values():
        entries.sort(key=lambda entry: entry[0])
    return by_phone


def _match_work_order(
    lead: WebsiteLead, candidates: list[tuple[datetime, uuid.UUID, str]]
) -> tuple[uuid.UUID | None, str | None]:
    """The earliest work order on this phone created after the lead itself
    - the one most plausibly caused by it, not some older unrelated visit
    (candidates are pre-sorted oldest-first, see _work_orders_by_phone)."""
    for created_at, work_order_id, external_number in candidates:
        if created_at > lead.created_at:
            return work_order_id, external_number
    return None, None


def list_leads(db: Session, *, now: datetime | None = None) -> list[LeadWithStatus]:
    """Every lead ever received, newest first, each with its computed
    status - feeds the full "Заявки" page."""
    now = now or datetime.now(UTC)
    settings = get_leads_settings(db)
    stale_cutoff = now - timedelta(days=settings.stale_after_days)

    leads = list(db.scalars(select(WebsiteLead).order_by(WebsiteLead.created_at.desc())))
    resolving = _resolving_calls_by_phone(db)
    work_orders = _work_orders_by_phone(db)
    result = []
    for lead in leads:
        work_order_id, work_order_number = _match_work_order(lead, work_orders.get(lead.phone, []))
        result.append(
            LeadWithStatus(
                lead=lead,
                status=_status_for(lead, resolving.get(lead.phone, []), stale_cutoff=stale_cutoff),
                matched_work_order_id=work_order_id,
                matched_work_order_number=work_order_number,
            )
        )
    return result


def get_open_leads(db: Session, *, now: datetime | None = None) -> list[WebsiteLead]:
    """Leads that still need a callback - not yet reached by a real call,
    either direction, and not yet past stale_after_days - feeds the
    Planner's envelope badge. Newest first."""
    return [item.lead for item in list_leads(db, now=now) if item.status == "open"]


def list_calls_for_lead(db: Session, lead: WebsiteLead) -> list[CallRecord]:
    """Every call (either direction) to/from this lead's own phone number -
    product ask, 2026-10-21: a lead's expanded detail card shows its call
    history (who called whom, when, the transcript, a PLAY button),
    because finding the one matching call by phone number inside the full
    Телефония page is impractical. `lead.phone` and `CallRecord.client` are
    already normalized the exact same way (last 10 digits - see
    _normalize_phone/zeon_client._norm_phone), so a plain equality match is
    enough - no further normalization needed here. Oldest first, same
    chronological convention as telephony_stats_service.list_line_calls's
    own drill-down."""
    return list(
        db.scalars(
            select(CallRecord)
            .where(CallRecord.client == lead.phone)
            .order_by(CallRecord.occurred_at)
        )
    )
