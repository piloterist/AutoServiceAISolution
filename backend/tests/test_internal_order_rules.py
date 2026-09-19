"""Unit tests for services/internal_order_rules.py - pure functions, no DB.

Faithful port of CarServiceOrderAnalitics' insurance_analytics.py rules
(extract_vin, norm_org, is_physical_person, internal_order_allowed); these
tests pin down the exact edge cases that logic depends on.
"""

from app.services.internal_order_rules import (
    ORG_PAN_MOTORS,
    ORG_PAN_OKSANA,
    ORG_PAN_STANISLAV,
    ORG_SOKOLOVA,
    internal_order_allowed,
    is_external_repair_type,
    is_physical_person,
    norm_org,
    normalize_vin,
)


def test_normalize_vin_accepts_a_valid_vin() -> None:
    assert normalize_vin("WVWZZZ1JZXW000001") == "WVWZZZ1JZXW000001"


def test_normalize_vin_uppercases_and_trims() -> None:
    assert normalize_vin("  wvwzzz1jzxw000001  ") == "WVWZZZ1JZXW000001"


def test_normalize_vin_rejects_wrong_length() -> None:
    assert normalize_vin("WVWZZZ1JZXW00001") is None  # 16 chars
    assert normalize_vin("WVWZZZ1JZXW0000011") is None  # 18 chars


def test_normalize_vin_rejects_forbidden_letters() -> None:
    # I, O, Q are never valid in a real VIN.
    assert normalize_vin("WVWZZZ1JZXWI00001") is None
    assert normalize_vin("WVWZZZ1JZXWO00001") is None
    assert normalize_vin("WVWZZZ1JZXWQ00001") is None


def test_normalize_vin_rejects_none_and_empty() -> None:
    assert normalize_vin(None) is None
    assert normalize_vin("") is None


def test_normalize_vin_does_not_extract_from_free_text() -> None:
    """Unlike the reference tool's extract_vin, this does NOT dig a VIN out
    of surrounding text - work_orders.vin is a dedicated field now, and a
    value that isn't itself a clean VIN is just invalid."""
    assert normalize_vin("VW TIGUAN VIN WVWZZZ1JZXW000001") is None


def test_is_external_repair_type() -> None:
    assert is_external_repair_type("Страховой") is True
    assert is_external_repair_type("Плановое ТО") is False
    assert is_external_repair_type(None) is False


def test_norm_org_collapses_whitespace_and_uppercases() -> None:
    assert norm_org("  ооо  ромашка  ") == "ООО РОМАШКА"


def test_norm_org_empty() -> None:
    assert norm_org(None) == ""
    assert norm_org("") == ""


def test_is_physical_person_true_for_a_plain_name() -> None:
    assert is_physical_person("Иванов Иван Иванович") is True


def test_is_physical_person_false_for_empty_payer() -> None:
    # Intentional asymmetry from the reference implementation: an empty
    # payer is NOT a physical person.
    assert is_physical_person(None) is False
    assert is_physical_person("") is False


def test_is_physical_person_false_for_word_boundary_markers() -> None:
    assert is_physical_person('ООО "Ромашка"') is False
    assert is_physical_person("ИП Сидоров") is False
    assert is_physical_person("АО Завод") is False


def test_is_physical_person_true_when_marker_is_not_a_whole_word() -> None:
    # "АО" must match as a whole word - "МАОВ" contains "АО" as a substring
    # but not as a standalone word, so this must NOT trip the marker.
    assert is_physical_person("Маов Иван Петрович") is True


def test_is_physical_person_false_for_substring_markers() -> None:
    assert is_physical_person("Страховая компания Согласие") is False
    assert is_physical_person("ПАО Сбербанк") is False


def test_internal_order_allowed_pan_stanislav_requires_non_physical_payer() -> None:
    assert internal_order_allowed(ORG_PAN_STANISLAV, "ООО Ромашка") is True
    assert internal_order_allowed(ORG_PAN_STANISLAV, "Иванов Иван Иванович") is False
    # Empty payer counts as "not a physical person" for this org.
    assert internal_order_allowed(ORG_PAN_STANISLAV, None) is True
    assert internal_order_allowed(ORG_PAN_STANISLAV, "") is True


def test_internal_order_allowed_pan_oksana_always_true() -> None:
    assert internal_order_allowed(ORG_PAN_OKSANA, "Иванов Иван Иванович") is True
    assert internal_order_allowed(ORG_PAN_OKSANA, None) is True


def test_internal_order_allowed_pan_motors_always_true() -> None:
    assert internal_order_allowed(ORG_PAN_MOTORS, "Иванов Иван Иванович") is True
    assert internal_order_allowed(ORG_PAN_MOTORS, None) is True


def test_internal_order_allowed_sokolova_empty_payer() -> None:
    assert internal_order_allowed(ORG_SOKOLOVA, None) is True
    assert internal_order_allowed(ORG_SOKOLOVA, "   ") is True


def test_internal_order_allowed_sokolova_payer_is_pan_oksana() -> None:
    assert internal_order_allowed(ORG_SOKOLOVA, ORG_PAN_OKSANA) is True
    assert internal_order_allowed(ORG_SOKOLOVA, "  ип пан оксана игоревна  ") is True


def test_internal_order_allowed_sokolova_payer_is_pan_motors() -> None:
    assert internal_order_allowed(ORG_SOKOLOVA, ORG_PAN_MOTORS) is True
    assert internal_order_allowed(ORG_SOKOLOVA, "  пан-моторс,   ооо  ") is True


def test_internal_order_allowed_sokolova_payer_is_pan_stanislav() -> None:
    assert internal_order_allowed(ORG_SOKOLOVA, ORG_PAN_STANISLAV) is True


def test_internal_order_allowed_sokolova_unrelated_company_rejected() -> None:
    """Deliberately an exact whitelist, not "any non-physical-person
    payer" - a genuine third-party customer paying for their own repair
    (e.g. "ООО Дело Техники", from the СЛ00000310 case) must NOT count as
    internal just for being a company."""
    assert internal_order_allowed(ORG_SOKOLOVA, "ООО Ромашка") is False
    assert internal_order_allowed(ORG_SOKOLOVA, "ООО Дело Техники") is False


def test_internal_order_allowed_sokolova_physical_payer_rejected() -> None:
    assert internal_order_allowed(ORG_SOKOLOVA, "Иванов Иван Иванович") is False


def test_internal_order_allowed_unknown_organization_never_allowed() -> None:
    assert internal_order_allowed("ИП Совершенно Другое Лицо", None) is False
    assert internal_order_allowed("ИП Совершенно Другое Лицо", "ООО Ромашка") is False
    assert internal_order_allowed(None, None) is False


def test_internal_order_allowed_org_normalization() -> None:
    # Extra whitespace/case in the organization name must still match.
    assert internal_order_allowed("  пан-моторс,   ооо  ", None) is True
