"""Unit tests for services/internal_order_rules.py - pure functions, no DB.

Faithful port of CarServiceOrderAnalitics' insurance_analytics.py rules
(extract_vin, norm_org, is_physical_person, internal_order_allowed); these
tests pin down the exact edge cases that logic depends on.
"""

from datetime import datetime
from types import SimpleNamespace

from app.services.internal_order_rules import (
    ORG_PAN_MOTORS,
    ORG_PAN_OKSANA,
    ORG_PAN_STANISLAV,
    ORG_SOKOLOVA,
    classify_car_group,
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
    # I and Q are never valid in a real VIN, and aren't auto-corrected (see
    # normalize_vin's own docstring for why "O" below is different).
    assert normalize_vin("WVWZZZ1JZXWI00001") is None
    assert normalize_vin("WVWZZZ1JZXWQ00001") is None


def test_normalize_vin_corrects_letter_o_to_zero() -> None:
    """ "O" is never legitimate in a real VIN either, but - unlike I/Q - any
    "O" found is corrected to "0" rather than rejected: confirmed live,
    2026-10-07, two real ЗН on the same real car both carried the same "O"
    typo from 1C's own vehicle catalog, which broke their car_key match
    (see internal_order_rules.py's own docstring)."""
    assert normalize_vin("WVWZZZ1JZXWO00001") == "WVWZZZ1JZXW000001"
    assert normalize_vin("5N1DLOMM1KC564548") == "5N1DL0MM1KC564548"


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


def test_is_physical_person_false_for_broadened_org_markers() -> None:
    """Added 2026-10-17 for the "Физ.лицо" list filter - confirmed against
    real prod customer_name values that previously slipped through as
    "physical person" despite clearly being organizations."""
    assert is_physical_person('ФГУП "Дирекция по инвестиционной деятельности"') is False
    assert is_physical_person("ФГБУ «РЭА» Минэнерго России") is False
    assert is_physical_person('АНО по развитию городской среды "МВС СТ"') is False
    assert is_physical_person("Общество с ограниченной ответственностью Газпромбанк") is False
    assert is_physical_person("ГУП Мосгортранс") is False
    assert is_physical_person("ТСЖ Ромашка") is False


def test_is_physical_person_false_for_quoted_or_all_caps_run() -> None:
    """Real miss, 2026-10-18: 'НОЧУ "Британская международная школа"'
    slipped through every marker above (НОЧУ wasn't one) - two general
    structural tells catch this family of cases instead of needing a
    marker for every possible abbreviation: a quoted name, or a run of 3+
    capital letters standing out inside an otherwise mixed-case string."""
    assert is_physical_person('НОЧУ "Британская международная школа"') is False
    assert is_physical_person("НИЦ Курчатовский институт") is False  # caps run, no quotes
    assert is_physical_person("Иванов Иван 'Торговый дом'") is False  # quotes, no marker/caps run


def test_is_physical_person_true_for_real_name_stored_entirely_in_caps() -> None:
    """The caps-run check must NOT trip on a string that's uppercase
    throughout - confirmed against real prod customer_name values,
    2026-10-18: several are a genuine individual's full name stored
    entirely in caps (not an abbreviation standing out in otherwise
    mixed-case text), e.g. "КИЛЬДИН ВЛАДИМИР АНАТОЛЬЕВИЧ". Applying the
    caps rule unconditionally would misclassify these as a legal entity -
    the opposite mistake from the one being fixed."""
    assert is_physical_person("КИЛЬДИН ВЛАДИМИР АНАТОЛЬЕВИЧ") is True
    assert is_physical_person("ЮРИЙ") is True


PAYERS = (ORG_PAN_MOTORS, ORG_PAN_STANISLAV, ORG_PAN_OKSANA)


def test_internal_order_allowed_for_every_organization_with_an_allowed_payer() -> None:
    for organization in (ORG_PAN_STANISLAV, ORG_PAN_OKSANA, ORG_PAN_MOTORS, ORG_SOKOLOVA):
        for payer in PAYERS:
            assert internal_order_allowed(organization, payer) is True, (organization, payer)


def test_internal_order_allowed_payer_must_be_one_of_the_three() -> None:
    """Product ask, 2026-10-28: only ПАН-МОТОРС ООО, ИП Пан Станислав Вячеславович and
    ИП Пан Оксана Игоревна may pay for an internal order - a company, a person or an
    empty payer never qualifies, under any organization."""
    for organization in (ORG_PAN_STANISLAV, ORG_PAN_OKSANA, ORG_PAN_MOTORS, ORG_SOKOLOVA):
        for payer in ("ООО Ромашка", "ООО Дело Техники", "Иванов Иван Иванович", None, "", "   "):
            assert internal_order_allowed(organization, payer) is False, (organization, payer)


def test_internal_order_allowed_unknown_organization_never_allowed() -> None:
    for payer in (*PAYERS, None, "ООО Ромашка"):
        assert internal_order_allowed("ИП Совершенно Другое Лицо", payer) is False
    assert internal_order_allowed(None, ORG_PAN_MOTORS) is False


def test_internal_order_allowed_normalizes_organization_and_payer() -> None:
    assert internal_order_allowed("  пан-моторс,   ооо  ", "  ип пан оксана игоревна  ") is True
    assert internal_order_allowed(ORG_SOKOLOVA, "  пан-моторс,   ооо  ") is True


# --- classify_car_group: an empty payer (warranty) follows the car's history ---

OURS = "ПАН-МОТОРС, ООО"
SOKOLOVA = "ИП Соколова Марина Эмильевна"


def _row(number, day, repair_type, payer, organization=SOKOLOVA):
    return SimpleNamespace(
        id=number,
        external_number=number,
        document_date=datetime(2026, 5, day),
        repair_type=repair_type,
        organization=organization,
        payer_name=payer,
    )


def test_warranty_follows_the_latest_earlier_non_external_order() -> None:
    ours = classify_car_group(
        [
            _row("EXT", 1, "Страховой", "СПАО Ингосстрах"),
            _row("OWN", 2, "Текущий", OURS),
            _row("W", 3, "Гарантийный", ""),
        ]
    )
    assert ours["W"] is True and ours["OWN"] is True and ours["EXT"] is False

    client = classify_car_group(
        [
            _row("EXT", 1, "Страховой", "СПАО Ингосстрах"),
            _row("OWN", 2, "Текущий", OURS),
            _row("CLIENT", 3, "Текущий", "Антюшин Святослав Сергеевич"),
            _row("W", 4, "Гарантийный", ""),
        ]
    )
    assert client["W"] is False and client["CLIENT"] is False


def test_warranty_after_a_single_external_order_is_internal() -> None:
    result = classify_car_group(
        [_row("EXT", 1, "Страховой", "СПАО Ингосстрах"), _row("W", 2, "Гарантийный", "")]
    )
    assert result["W"] is True


def test_warranty_without_earlier_orders_or_after_several_external_ones_is_not_internal() -> None:
    first = classify_car_group([_row("EXT", 5, "Страховой", "X"), _row("W", 1, "Гарантийный", "")])
    assert first["W"] is False
    several = classify_car_group(
        [
            _row("E1", 1, "Страховой", "X"),
            _row("E2", 2, "Страховой", "X"),
            _row("W", 3, "Гарантийный", ""),
        ]
    )
    assert several["W"] is False


def test_warranty_on_a_car_without_external_orders_is_not_internal() -> None:
    result = classify_car_group([_row("OWN", 1, "Текущий", OURS), _row("W", 2, "Гарантийный", "")])
    assert result == {"OWN": False, "W": False}


def test_filled_payer_keeps_the_plain_rule() -> None:
    result = classify_car_group(
        [
            _row("EXT", 1, "Страховой", "X"),
            _row("A", 2, "Текущий", OURS),
            _row("B", 3, "Текущий", "Иванов Иван"),
            _row("C", 4, "Текущий", OURS, organization="ООО Левая"),
        ]
    )
    assert (result["A"], result["B"], result["C"]) == (True, False, False)
