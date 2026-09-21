// Plain constants shared between server-only code (lib/backend-api.ts) and
// client components (components/settings/*) - kept out of backend-api.ts
// itself because that file is "server-only" and throws if a client
// component imports anything from it at runtime, even just for a constant
// array (type-only imports are fine there since TypeScript erases them,
// but these are real values used in .map() rendering).

// Mirrors backend app/models/workshop.py's WORKSHOP_TYPES.
export const WORKSHOP_TYPES = ["Кузовной", "Слесарный"] as const;
export type WorkshopType = (typeof WORKSHOP_TYPES)[number];

// Mirrors backend app/models/user.py's ROLES.
export const USER_ROLES = ["Админ", "Управляющий", "Мастер приёмщик", "Бухгалтер", "Сотрудник"] as const;
export type UserRole = (typeof USER_ROLES)[number];
