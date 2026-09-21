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
CAR_STATUSES = (CAR_STATUS_ACCEPT, CAR_STATUS_IN_PROGRESS, CAR_STATUS_WAITING, CAR_STATUS_DONE)

# Кузовной этап - each BodyCarStage row picks one of these.
BODY_STAGE_TYPES = (
    "Приёмка",
    "Разбор",
    "Жесть",
    "Подготовка",
    "Окраска",
    "Сборка",
    "Полировка",
    "Выдача",
    "Ответ от СК",
    "Ждём з/ч",
    "Оплата",
    "Другое",
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
