"""Цех determination for each imported call - see models/
workshop_phone_mapping.py for the operator-maintained "Цех — Телефон —
Добавочный" table this matches against, and models/call_record.py's
WORKSHOP_SOURCE_* constants for the possible outcomes.

Pure function of already-imported data (CallRecord.dst/exten/
rang_extensions, parsed by zeon_client.py at fetch time, or backfilled here
straight from raw_payload for calls imported before this feature existed -
confirmed present there for every call already on file, so backfilling
never needs a second Zeon API call) - this never needs its own background
relay loop. It runs synchronously at import time (see
telephony_import_service._upsert_calls) and on demand via recompute_all
(the Settings "Пересчитать цеха" button, and the one-time historical
backfill/reassignment after the mapping table changes).
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.call_record import (
    CALL_TYPE_OUT,
    WORKSHOP_SOURCE_IVR_NO_ANSWER,
    WORKSHOP_SOURCE_LINE,
    WORKSHOP_SOURCE_MULTIPLE,
    WORKSHOP_SOURCE_NO_MATCH,
    WORKSHOP_SOURCE_OPERATOR,
    WORKSHOP_SOURCE_RING_GROUP,
    CallRecord,
)
from app.models.workshop_phone_mapping import WorkshopPhoneMapping

RECOMPUTE_BATCH_SIZE = 500


def normalize_phone_or_line(value: str | None) -> str:
    """ "+79261537227" / "89261537227" / "9261537227" -> "79261537227";
    anything else (an advertising/IVR line name like "pan2", or a line code
    that only looks numeric, e.g. "0005348") -> itself, lowercased - see
    models/workshop_phone_mapping.py's own docstring. Applied identically to
    a mapping row's own `phone` (on save - see workshop_phone_mapping_service)
    and to each call's `dst` (at match time), so the two sides always
    compare equal regardless of which raw format either one showed up in."""
    text = (value or "").strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits[0] in ("7", "8"):
        return "7" + digits[1:]
    if len(digits) == 10:
        return "7" + digits
    return text.lower()


def _split_exts(value: Any) -> list[str]:
    # Same splitting rule as zeon_client._split_exts (members/lost are
    # colon/comma/semicolon/whitespace-separated) - duplicated rather than
    # imported since that one is a private helper of an unrelated module.
    return [p for p in re.split(r"[:,;\s]+", str(value or "")) if p]


class WorkshopIndex:
    """Loaded once per recompute pass (not once per call) from the current
    workshop_phone_mappings rows."""

    def __init__(self, db: Session) -> None:
        by_phone: dict[str, set[uuid.UUID]] = defaultdict(set)
        by_extension: dict[str, set[uuid.UUID]] = defaultdict(set)
        for mapping in db.scalars(select(WorkshopPhoneMapping)):
            if mapping.phone:
                by_phone[normalize_phone_or_line(mapping.phone)].add(mapping.workshop_id)
            if mapping.extension:
                by_extension[mapping.extension.strip().lower()].add(mapping.workshop_id)
        self._by_phone = dict(by_phone)
        self._by_extension = dict(by_extension)

    def phone_workshops(self, dst: str | None) -> set[uuid.UUID]:
        if not dst:
            return set()
        return self._by_phone.get(normalize_phone_or_line(dst), set())

    def extension_workshops(self, extension: str | None) -> set[uuid.UUID]:
        if not extension:
            return set()
        return self._by_extension.get(extension.strip().lower(), set())


def phone_extension_index(db: Session) -> tuple[dict[str, set[str]], dict[str, str]]:
    """For the "Куда звонили"/"Кто ответил" columns in the per-line call
    drill-down (see telephony_stats_service.list_line_calls) - distinct
    from WorkshopIndex above, which only cares which workshop(s) a phone/
    extension points to, not which добавочные a given phone/line actually
    rings to. Confirmed against the real, fully-filled-in table
    (2026-10-04): a line routinely rings several добавочные (ring group),
    AND the same добавочный can legitimately repeat across two totally
    unrelated lines/departments (e.g. "301" is both Солнцево-Кузовной's own
    line and one of Каховка-Слесарный's) - so there is no clean, globally
    unambiguous добавочный->phone pairing to fall back on in general; the
    *call's own* dst is what disambiguates a shared добавочный, per product
    feedback: "вначале всегда старайся определить по тому куда звонили...
    а потом уже по тому, кто ответил".

    Returns:
    - extensions_by_phone: normalized phone -> every добавочный configured
      to ring on that line. The caller uses this to check whether the
      answering добавочный is actually one of *this call's own* dst's
      добавочные - if so, dst's own phone is unambiguously the answering
      phone too, regardless of whether that добавочный also appears under
      some other, unrelated phone elsewhere in the table.
    - fallback_phone_by_extension: добавочный -> phone, only for a
      добавочный that appears under exactly one distinct phone across the
      WHOLE table - a last-resort guess for a call whose own dst didn't
      match anything (or wasn't answered by one of dst's own добавочные),
      dropped entirely (not guessed) when genuinely ambiguous.
    """
    extensions_by_phone: dict[str, set[str]] = defaultdict(set)
    ext_phone_candidates: dict[str, set[str]] = defaultdict(set)
    rows = db.scalars(
        select(WorkshopPhoneMapping).where(
            WorkshopPhoneMapping.phone.is_not(None),
            WorkshopPhoneMapping.extension.is_not(None),
        )
    )
    for mapping in rows:
        phone = mapping.phone or ""
        ext = (mapping.extension or "").strip().lower()
        if not phone or not ext:
            continue
        extensions_by_phone[phone].add(ext)
        ext_phone_candidates[ext].add(phone)
    fallback_phone_by_extension = {
        ext: next(iter(phones)) for ext, phones in ext_phone_candidates.items() if len(phones) == 1
    }
    return dict(extensions_by_phone), fallback_phone_by_extension


def determine_workshop(
    *,
    call_type: str,
    dst: str | None,
    exten: str | None,
    rang_extensions: list[str] | None,
    index: WorkshopIndex,
) -> tuple[uuid.UUID | None, str]:
    """The product rule, in order:

    Outbound: by `exten` (с какого добавочного звонили) only - `dst` for an
    OUT call is the external number being dialed, not a цех signal.

    Inbound (and the rare LOCAL/TRANSIT/UNKNOWN types - treated the same,
    there's no separate rule for those):
    1. By `dst` (куда звонили) - exactly one цех among matching rows.
    2. Else by `exten` (кто ответил).
    3. Else by the union of every extension the call rang on at all
       (`rang_extensions` - already combines Zeon's members+lost at import
       time), for a missed call where nobody happened to answer.
    4. Else "Не определён", with a specific reason: multiple disagreeing
       workshops among matches at any step, no match anywhere, or (if
       `exten` was empty throughout) likely an IVR/queue nobody picked up.
    """
    if call_type == CALL_TYPE_OUT:
        matches = index.extension_workshops(exten)
        if len(matches) == 1:
            return next(iter(matches)), WORKSHOP_SOURCE_OPERATOR
        if len(matches) > 1:
            return None, WORKSHOP_SOURCE_MULTIPLE
        return None, WORKSHOP_SOURCE_NO_MATCH

    phone_matches = index.phone_workshops(dst)
    if len(phone_matches) == 1:
        return next(iter(phone_matches)), WORKSHOP_SOURCE_LINE
    if len(phone_matches) > 1:
        return None, WORKSHOP_SOURCE_MULTIPLE

    ext_matches = index.extension_workshops(exten)
    if len(ext_matches) == 1:
        return next(iter(ext_matches)), WORKSHOP_SOURCE_OPERATOR
    if len(ext_matches) > 1:
        return None, WORKSHOP_SOURCE_MULTIPLE

    ring_matches: set[uuid.UUID] = set()
    for extension in rang_extensions or []:
        ring_matches |= index.extension_workshops(extension)
    if len(ring_matches) == 1:
        return next(iter(ring_matches)), WORKSHOP_SOURCE_RING_GROUP
    if len(ring_matches) > 1:
        return None, WORKSHOP_SOURCE_MULTIPLE

    if not exten:
        return None, WORKSHOP_SOURCE_IVR_NO_ANSWER
    return None, WORKSHOP_SOURCE_NO_MATCH


def fields_from_raw_payload(raw: dict[str, Any]) -> tuple[str | None, str | None, list[str]]:
    """Extracts dst/exten/rang_extensions from a stored raw_payload - used
    to backfill rows imported before these columns existed (see
    recompute_all), without a Zeon API call."""
    dst = str(raw.get("dst") or "") or None
    exten = str(raw.get("exten") or "") or None
    members = _split_exts(raw.get("members"))
    lost = _split_exts(raw.get("lost"))
    rang_extensions = sorted(set(members) | set(lost))
    return dst, exten, rang_extensions


def recompute_all(db: Session, *, batch_size: int = RECOMPUTE_BATCH_SIZE) -> int:
    """Backfills dst/exten/rang_extensions from raw_payload for any call
    still missing them (cheap, no Zeon call - see module docstring), then
    (re)assigns workshop_id/workshop_source for every call against the
    current workshop_phone_mappings table.

    Always recomputes every row from scratch, not just "new" ones - an
    edited/deleted mapping row can change an already-assigned call's
    outcome, so this must be safe (and correct) to re-run in full any time
    the mapping table changes (the Settings "Пересчитать цеха" button), not
    only once at initial rollout. Returns the number of calls processed.
    """
    index = WorkshopIndex(db)
    processed = 0
    offset = 0
    while True:
        calls = list(
            db.scalars(select(CallRecord).order_by(CallRecord.id).limit(batch_size).offset(offset))
        )
        if not calls:
            break
        for call in calls:
            if (
                call.dst is None
                and call.exten is None
                and not call.rang_extensions
                and call.raw_payload
            ):
                dst, exten, rang_extensions = fields_from_raw_payload(call.raw_payload)
                call.dst = dst
                call.exten = exten
                call.rang_extensions = rang_extensions or None
            workshop_id, source = determine_workshop(
                call_type=call.call_type,
                dst=call.dst,
                exten=call.exten,
                rang_extensions=call.rang_extensions,
                index=index,
            )
            call.workshop_id = workshop_id
            call.workshop_source = source
            processed += 1
        db.commit()
        offset += batch_size
    return processed
