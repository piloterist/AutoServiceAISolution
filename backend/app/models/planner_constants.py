"""Closed value sets for the Planner (Слесарный/Кузовной цех) that the
product brief describes as picked "from a list" but didn't ask for a
Settings table to manage - unlike SlesarkaStatus (which does have one).
Hardcoded here for the same reason WorkOrder-adjacent role/workshop-type
constants live next to their models (see models/user.py, models/workshop.py).
"""

# Кузовной car-level status - the prototype's CAR_ST, not the same thing as
# a "этап" (BODY_STAGE_TYPES below) or a Слесарный SlesarkaStatus row.
CAR_STATUS_ACCEPT = "К приёмке"
CAR_STATUS_IN_PROGRESS = "В работе"
CAR_STATUS_WAITING = "Ожидание"
CAR_STATUS_DONE = "Выдан"
# These two are display-only overrides on the Planner (see BodyView.tsx):
# regardless of the car's actual этапы/dates, it's shown as a single pale
# bar spanning ±3 months from created_at, and always sorted to the very
# end of the car list - a car "waiting on a decision" or "ready, just
# sitting there" isn't meaningfully placed on a day-by-day этап timeline.
CAR_STATUS_APPROVAL = "Согласование"
CAR_STATUS_READY_FOR_PICKUP = "Готова к выдаче"
CAR_STATUSES = (
    CAR_STATUS_ACCEPT,
    CAR_STATUS_IN_PROGRESS,
    CAR_STATUS_WAITING,
    CAR_STATUS_DONE,
    CAR_STATUS_APPROVAL,
    CAR_STATUS_READY_FOR_PICKUP,
)

# Кузовной этап - each BodyCarStage row picks one of these.
BODY_STAGE_TYPES = (
    "Осмотр",
    "Приёмка",
    "Разбор",
    "Дефектовка",
    "Жесть",
    "Подготовка",
    "Окраска",
    "Сборка-Полировка",
    "Выдача",
    "Ответ от СК",
    "Ждём з/ч",
    "Оплата",
    "Другое",
)

# Кузовной Planner "Вид ремонта" filter (BodyView.tsx) + Settings ->
# Пользователи -> "Вид ремонта по умолчанию" (User.default_repair_type) -
# per product feedback, 2026-09-30. Not the same closed set as a real
# WorkOrder.repair_type value (1C's own ЗаказНаряд.ВидРемонта text, e.g.
# "Страховой"/"Гарантийный"/"Гарантийный (бесплатный)"/"Текущий"/"Основной"/
# ...) - "Текущий" here is a catch-all bucket for every ЗН that isn't
# Гарантийный/Гарантийный (бесплатный)/Страховой, not a literal repair_type
# match. The actual car<->bucket matching only ever happens client-side
# (BodyView.tsx's carMatchesRepairTypeFilter) since BodyCar.repair_type is
# read live from the linked ЗН, never stored - this tuple exists purely to
# validate User.default_repair_type at the schema layer.
REPAIR_TYPE_FILTER_ALL = "Все"
REPAIR_TYPE_FILTER_CURRENT = "Текущий"
REPAIR_TYPE_FILTER_WARRANTY = "Гарантийный"
REPAIR_TYPE_FILTER_INSURANCE = "Страховой"
REPAIR_TYPE_FILTERS = (
    REPAIR_TYPE_FILTER_ALL,
    REPAIR_TYPE_FILTER_CURRENT,
    REPAIR_TYPE_FILTER_WARRANTY,
    REPAIR_TYPE_FILTER_INSURANCE,
)

# Assigned round-robin to new BodyCar rows (product brief: "цвет машины на
# графике не надо указывать, просто имею 6-10 цветовых вариантов и
# чередуй их при создании записи").
BODY_CAR_COLORS = (
    "#93c5fd",
    "#f9a8d4",
    "#86efac",
    "#fcd34d",
    "#c4b5fd",
    "#fdba74",
    "#5eead4",
    "#fca5a5",
)
