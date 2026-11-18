"""Приведение полей заявки с сайта к нашим именам (`user_phone`, `form_name`, `quiz_damage`, ...).

Сайты шлют заявки по-разному: WordPress-сайт pan-motors.ru - с нашими именами полей, сайт
panmotors77.ru (выгрузка Webflow) - обычной формой с именами из разметки («Phone number», «Форма»,
«Bamper», ...). Приём не должен терять заявку из-за другого названия поля, поэтому всё, что
узнаём, переименовываем здесь; неизвестные поля остаются как есть (их видно в карточке заявки).

PHP превращает пробелы и точки в именах полей в подчёркивания («Phone number» -> «Phone_number»),
поэтому имена сравниваются без регистра, пробелов, подчёркиваний и дефисов.
"""

from __future__ import annotations

import re
from typing import Any

# Повреждённые элементы квиза (чекбоксы со значением «on») -> названия для карточки.
DAMAGE_LABELS = {
    "bagazhnik": "Багажник",
    "zadnjajadver": "Дверь задняя",
    "perednjajadver": "Дверь передняя",
    "porog": "Порог",
    "perednekrilo": "Крыло переднее",
    "zadnekrilo": "Крыло заднее",
    "bamper": "Бампер",
    "kapot": "Капот",
    "krisha": "Крыша",
    "drugoepovrezhdenie": "Другое повреждение",
}

# Просто переименовать: имя (в канонической записи) -> наше имя.
RENAMES = {
    "форма": "form_name",
    "страница": "page_url",
    "advchannel": "adv_channel",
    "budget": "quiz_budget",
    "summa": "quiz_budget_sum",
    "gift": "quiz_gift",
    "evakuator": "quiz_evacuator",
    "message": "quiz_messenger",
    "nophoto": "quiz_damage_photo_not",
    "promokod": "user_connection",
    "question": "question",
    "evacuateadrress": "evacuate_address",
    "evacuateaddress": "evacuate_address",
}

# Служебные поля формы сайта: в заявке не нужны.
DROPPED = {"requiredfields", "sendto"}

_TRUE = {"on", "1", "true", "yes", "да", "y"}
_QUIZ_MARKERS = (
    "quiz_budget",
    "quiz_gift",
    "quiz_evacuator",
    "quiz_messenger",
    "quiz_damage_photo_not",
)
_NAME = re.compile(r"^(name|имя)\d*$")


def _canonical(key: str) -> str:
    return re.sub(r"[\s_\-.]+", "", key.lower())


def _text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return "" if value is None else str(value).strip()


def normalize_site_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Новый словарь с нашими именами полей. Идемпотентно: заявка в нашем формате не меняется."""
    result: dict[str, Any] = {}
    damage: list[str] = []
    phone = _text(raw.get("user_phone"))
    name = _text(raw.get("user_name"))

    for key, value in raw.items():
        canon = _canonical(str(key))
        if canon in DROPPED:
            continue
        if canon in DAMAGE_LABELS:
            if _text(value).lower() in _TRUE:
                damage.append(DAMAGE_LABELS[canon])
            continue
        if "phone" in canon or "телефон" in canon:
            if not phone and _text(value):
                phone = _text(value)
            if str(key) != "user_phone":
                continue
        if _NAME.match(canon) and str(key) != "user_name":
            if not name and _text(value):
                name = _text(value)
            continue
        target = RENAMES.get(canon)
        if target and target not in raw and str(key) != target:
            result[target] = value if not isinstance(value, str) else value.strip()
            continue
        result[str(key)] = value

    if phone:
        result["user_phone"] = phone
    if name:
        result["user_name"] = name

    # Квиз «Кузов»: отмеченные повреждения и признаки квиза; ключ quiz_damage по нашей классификации
    # (leads_service._classify_source) и означает «заявка из кузовного квиза».
    is_quiz = (
        bool(damage)
        or any(marker in result for marker in _QUIZ_MARKERS)
        or str(result.get("form_name", "")).strip().lower() == "кузов"
    )
    if "quiz_damage" not in result and is_quiz:
        result["quiz_damage"] = {str(i + 1): label for i, label in enumerate(damage)}
    return result
