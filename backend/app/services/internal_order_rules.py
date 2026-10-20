"""Internal ("внутренний") work order detection - PanMotors-specific business rules.

Ported from the reference implementation in the separate
CarServiceOrderAnalitics tool (insurance_analytics.py: extract_vin,
norm_org, is_physical_person, internal_order_allowed, select_insurance_orders),
with one substitution: that tool derived "внешний" from the order number's
prefix (ПМ/КХ/ПО); here it's simply `repair_type == EXTERNAL_REPAIR_TYPE`
(ЗаказНаряд.ВидРемонта = "Страховой"), since that's already a real, imported
field. Everything downstream of that boolean (the org/payer rules, the
car-grouping) is a faithful port, not a reinterpretation.

This is deliberately hardcoded to PanMotors' own legal entities (the
ORG_* constants and their rules below) rather than made configurable - the
whole feature is explicitly client-specific ("Специфика PanMotors" in
Settings), unlike the rest of this codebase's status/department/repair-type
handling, which is always plain client data, never baked in (see
ARCHITECTURE.md). Isolated to this one module so a future multi-client
version can move it behind configuration without touching callers.

Car matching is VIN-only, with no text-fallback: an earlier reference
implementation matched by normalized "Автомобиль" free text when a VIN
wasn't found, but that was a workaround for not having a real VIN field.
Here work_orders.vin comes from 1C's own vehicle catalog
(Автомобиль.VIN), so a work order with no valid VIN simply can't be
grouped with any other - it never becomes "internal" (see
recompute_internal_flags in import_service.py: a None car_key is skipped
entirely, both as a candidate and as a match target).
"""

from __future__ import annotations

import re

# VIN charset excludes I, O, Q (too easily confused with 1/0) - standard
# across the industry, not a PanMotors-specific rule.
_VALID_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

_ORG_MARKER_PATTERNS = [
    re.compile(r"\bООО\b"),
    re.compile(r"\bОАО\b"),
    re.compile(r"\bПАО\b"),
    re.compile(r"\bНАО\b"),
    re.compile(r"\bЗАО\b"),
    re.compile(r"\bАО\b"),
    re.compile(r"\bИП\b"),
    # Broadened 2026-10-17 (product ask: "ФГБУ, ФГУП и прочее, любые
    # сокращения") for the new "Физ.лицо" list filter/highlight (see
    # endpoints/work_orders.py), which reuses this same function against
    # customer_name - confirmed against real prod customer_name values that
    # were previously slipping through as "physical person": ФГУП, ФГБУ,
    # АНО, and the spelled-out "Общество с ограниченной ответственностью".
    # The rest (ГУП/МУП/ГБУ/ГКУ/ФКУ/МБУ/МКУ/НКО/ТСЖ/СНТ/КФХ) are standard
    # Russian legal/organizational-form abbreviations added proactively,
    # same reasoning as the ones above even without their own confirmed hit.
    re.compile(r"\bФГУП\b"),
    re.compile(r"\bФГБУ\b"),
    re.compile(r"\bГУП\b"),
    re.compile(r"\bМУП\b"),
    re.compile(r"\bГБУ\b"),
    re.compile(r"\bГКУ\b"),
    re.compile(r"\bФКУ\b"),
    re.compile(r"\bМБУ\b"),
    re.compile(r"\bМКУ\b"),
    re.compile(r"\bНКО\b"),
    re.compile(r"\bАНО\b"),
    re.compile(r"\bТСЖ\b"),
    re.compile(r"\bСНТ\b"),
    re.compile(r"\bКФХ\b"),
    # НОЧУ (Негосударственное образовательное частное учреждение) - real
    # miss, 2026-10-18: 'НОЧУ "Британская международная школа"' slipped
    # through every marker above. Also caught independently by the new
    # structural checks below (an all-caps abbreviation + quotes), kept
    # here too as an explicit, direct fix for the exact reported case.
    re.compile(r"\bНОЧУ\b"),
    re.compile(r"ОБЩЕСТВО"),
    re.compile(r"СТРАХ"),
    re.compile(r"БАНК"),
    re.compile(r"ГРУПП"),
    re.compile(r"ХОЛДИНГ"),
    re.compile(r"КОМПАНИ"),
]

# Two structural tells, added 2026-10-18 after 'НОЧУ "Британская
# международная школа"' slipped through every marker above (НОЧУ wasn't
# one) despite both signals being present - see is_physical_person's own
# use of these, which explains the mixed-case guard on the caps one.
_CONSECUTIVE_CAPS_RUN = re.compile(r"[A-ZА-ЯЁ]{3,}")
_QUOTE_CHARS = re.compile(r"[\"'«»„]")

# ЗаказНаряд.ВидРемонта value that marks a work order "внешний" (страховой)
# for this specific PanMotors rule - distinct from, and unrelated to, the
# separately-configurable AppSettings.insurance_repair_type used by the
# existing insurance-reporting feature (settings_service.py). Hardcoded
# because this whole feature already is (see module docstring).
EXTERNAL_REPAIR_TYPE = "Страховой"

ORG_PAN_STANISLAV = "ИП ПАН СТАНИСЛАВ ВЯЧЕСЛАВОВИЧ"
ORG_PAN_OKSANA = "ИП ПАН ОКСАНА ИГОРЕВНА"
ORG_PAN_MOTORS = "ПАН-МОТОРС, ООО"
ORG_SOKOLOVA = "ИП СОКОЛОВА МАРИНА ЭМИЛЬЕВНА"


def normalize_vin(raw: str | None) -> str | None:
    """Uppercases/trims and validates as a real 17-character VIN (no I/Q -
    see the "O" note below).

    Returns None for anything that doesn't look like a real VIN - a missing
    value, a malformed one, or free text - rather than guessing. No token
    extraction/splitting: work_orders.vin is a dedicated structured field
    from 1C's vehicle catalog, not free text that might have a VIN buried
    inside it (contrast the reference tool's extract_vin, which had to dig
    a VIN out of a free-text "Автомобиль" column).

    One exception: a literal "O" is corrected to "0" before validating.
    "O" is never legitimate in a real VIN (excluded industry-wide
    specifically to avoid 0/O confusion - see _VALID_VIN's own comment),
    so any "O" present is virtually certainly a mistyped "0", not a
    different car - confirmed live, 2026-10-07: two real ЗН on the same
    real car (ПМ00000031/ЭПЭП002502, VIN 5N1DLOMM1KC564548, both from 1C's
    own vehicle catalog) carried the identical "O" typo, which silently
    broke their car_key match - and so the "Внутренний" flag - before this
    fix. "I"/"Q" are NOT corrected the same way - no equivalent real-world
    case has come up for those, and unlike "O" they aren't visually
    interchangeable with a single other character, so guessing would be
    more likely to paper over a genuinely different VIN.
    """
    if not raw:
        return None
    candidate = raw.strip().upper().replace("O", "0")
    return candidate if _VALID_VIN.fullmatch(candidate) else None


def norm_org(value: str | None) -> str:
    """Trim, collapse internal whitespace runs, uppercase. Used for both
    organization and payer comparisons throughout this module."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).upper()


def is_physical_person(payer: str | None) -> bool:
    """True if `payer` reads as an individual rather than a company/IP.

    Despite the parameter name, this is a plain text heuristic with no
    payer-specific meaning baked in - also reused as-is against
    WorkOrder.customer_name for the "Физ.лицо" list filter/highlight (see
    endpoints/work_orders.py's is_individual_customer), not just the
    internal-order payer rules below.

    An empty/missing payer is NOT treated as a physical person (returns
    False) - this asymmetry is intentional and matches the reference
    implementation exactly; it's why ORG_SOKOLOVA's rule below checks for
    an empty payer as its own separate allowed case rather than relying on
    this function to cover it.

    Two structural checks run first, against the ORIGINAL casing (before
    norm_org's own uppercasing, which would otherwise make every name look
    "all caps" too) - product ask, 2026-10-18, after 'НОЧУ "Британская
    международная школа"' read as a physical person despite having neither
    marker: "не может быть трёх и более заглавных букв подряд и не может
    быть кавычек - это явные признаки юрлица".

    - A literal quote character (ООО "Ромашка", НОЧУ "Школа") - a real
      person's name never has one, checked unconditionally.
    - A run of 3+ consecutive capital letters (an abbreviation: НОЧУ, НИЦ,
      ФГБОУВО, РПН...) - but ONLY when the rest of the string ISN'T also
      all-caps. Confirmed against real prod customer_name values,
      2026-10-18: several are a real individual's full name stored
      ENTIRELY in caps (e.g. "КИЛЬДИН ВЛАДИМИР АНАТОЛЬЕВИЧ") - applying
      this rule unconditionally would have flipped those real people into
      "legal entity" instead, trading one misclassification for another.
      Requiring at least one lowercase letter elsewhere restricts this to
      an abbreviation standing out INSIDE an otherwise mixed-case name,
      which a real all-caps person's name never has either.
    """
    raw = str(payer or "")
    if _QUOTE_CHARS.search(raw):
        return False
    if any(ch.islower() for ch in raw) and _CONSECUTIVE_CAPS_RUN.search(raw):
        return False
    text = norm_org(payer)
    if not text:
        return False
    return not any(pattern.search(text) for pattern in _ORG_MARKER_PATTERNS)


def is_external_repair_type(repair_type: str | None) -> bool:
    """ "Внешний" for this rule = ЗаказНаряд.ВидРемонта is the insurance
    repair type - see EXTERNAL_REPAIR_TYPE above."""
    return repair_type == EXTERNAL_REPAIR_TYPE


def internal_order_allowed(organization: str | None, payer: str | None) -> bool:
    """Whether a non-external work order on an "insurance car" (see
    recompute_internal_flags) actually counts as "внутренний", based on
    which PanMotors legal entity it was raised under and who pays. Any
    organization not in this fixed set never allows an internal order.
    """
    org = norm_org(organization)

    if org == ORG_PAN_STANISLAV:
        return not is_physical_person(payer)
    if org == ORG_PAN_OKSANA:
        return True
    if org == ORG_PAN_MOTORS:
        return True
    if org == ORG_SOKOLOVA:
        if not payer or not str(payer).strip():
            return True
        # Deliberately an exact whitelist, not "not a physical person" -
        # that broader check let any unrelated company (e.g. a genuine
        # third-party customer paying for their own repair) count as
        # internal just for being a legal entity, which is what flagged
        # СЛ00000310 (payer "ООО Дело Техники") incorrectly.
        return norm_org(payer) in (ORG_PAN_OKSANA, ORG_PAN_MOTORS, ORG_PAN_STANISLAV)
    return False
