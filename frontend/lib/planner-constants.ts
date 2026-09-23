// Mirrors backend app/models/planner_constants.py - plain values needed at
// runtime in client components (see lib/admin-constants.ts for why these
// can't just be `import type`-ed out of the server-only lib/backend-api.ts).

export const CAR_STATUSES = ["К приёмке", "В работе", "Ожидание", "Выдан"] as const;

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
