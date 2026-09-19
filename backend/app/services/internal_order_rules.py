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
    re.compile(r"\bЗАО\b"),
    re.compile(r"\bАО\b"),
    re.compile(r"\bИП\b"),
    re.compile(r"СТРАХ"),
    re.compile(r"БАНК"),
    re.compile(r"ГРУПП"),
    re.compile(r"ХОЛДИНГ"),
    re.compile(r"КОМПАНИ"),
]

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
    """Uppercases/trims and validates as a real 17-character VIN (no I/O/Q).

    Returns None for anything that doesn't look like a real VIN - a missing
    value, a malformed one, or free text - rather than guessing. No token
    extraction/splitting: work_orders.vin is a dedicated structured field
    from 1C's vehicle catalog, not free text that might have a VIN buried
    inside it (contrast the reference tool's extract_vin, which had to dig
    a VIN out of a free-text "Автомобиль" column).
    """
    if not raw:
        return None
    candidate = raw.strip().upper()
    return candidate if _VALID_VIN.fullmatch(candidate) else None


def norm_org(value: str | None) -> str:
    """Trim, collapse internal whitespace runs, uppercase. Used for both
    organization and payer comparisons throughout this module."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).upper()


def is_physical_person(payer: str | None) -> bool:
    """True if `payer` reads as an individual rather than a company/IP.

    An empty/missing payer is NOT treated as a physical person (returns
    False) - this asymmetry is intentional and matches the reference
    implementation exactly; it's why ORG_SOKOLOVA's rule below checks for
    an empty payer as its own separate allowed case rather than relying on
    this function to cover it.
    """
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
