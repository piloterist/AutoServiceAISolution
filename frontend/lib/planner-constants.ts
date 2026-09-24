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

export const BODY_STAGE_TYPES = [
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
