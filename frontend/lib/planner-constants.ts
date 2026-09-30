// Mirrors backend app/models/planner_constants.py - plain values needed at
// runtime in client components (see lib/admin-constants.ts for why these
// can't just be `import type`-ed out of the server-only lib/backend-api.ts).

export const CAR_STATUSES = [
  "К приёмке",
  "В работе",
  "Ожидание",
  "Выдан",
  "Согласование",
  "Готова к выдаче",
] as const;

// Display-only override statuses (see BodyView.tsx's carDisplaySpan/
// compareCars): regardless of the car's actual этапы/dates, shown as one
// pale bar spanning ±3 months from created_at, always sorted last.
export const CAR_STATUS_APPROVAL = "Согласование";
export const CAR_STATUS_READY_FOR_PICKUP = "Готова к выдаче";
export const SPECIAL_CAR_STATUSES = [CAR_STATUS_APPROVAL, CAR_STATUS_READY_FOR_PICKUP] as const;

// Кузовной Planner "Вид ремонта" filter (BodyView.tsx) + Settings ->
// Пользователи -> "Вид ремонта по умолчанию" - not the same closed set as
// a real WorkOrder.repair_type value (1C's own ЗаказНаряд.ВидРемонта text,
// e.g. "Страховой"/"Гарантийный"/"Гарантийный (бесплатный)"/"Текущий"/...) -
// "Текущий" here is a catch-all bucket for every ЗН that isn't
// Гарантийный/Гарантийный (бесплатный)/Страховой, not a literal match -
// see BodyView.tsx's carMatchesRepairTypeFilter.
export const REPAIR_TYPE_FILTERS = ["Все", "Текущий", "Гарантийный", "Страховой"] as const;
export type RepairTypeFilter = (typeof REPAIR_TYPE_FILTERS)[number];

export const BODY_STAGE_TYPES = [
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
] as const;
