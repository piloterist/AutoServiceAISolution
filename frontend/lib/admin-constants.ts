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

// Mirrors backend app/models/user.py's THEMES - values match the frontend's
// own `data-theme` attribute directly, so only this label needs mapping.
export const USER_THEMES = [
  { value: "light", label: "Светлая" },
  { value: "dark", label: "Тёмная" },
] as const;
export type UserTheme = (typeof USER_THEMES)[number]["value"];

// Mirrors backend app/models/employee.py's SPECIALTIES.
export const SPECIALTIES = [
  "Жестянщик",
  "Маляр",
  "Арматурщик",
  "Механик",
  "Мастер приёмщик",
  "Администратор",
] as const;
export type Specialty = (typeof SPECIALTIES)[number];

// Mirrors backend app/models/phone_source.py's SOURCE_GROUPS.
export const PHONE_SOURCE_GROUPS = ["Карты и каталоги", "Прямые номера", "Прочие"] as const;
export type PhoneSourceGroup = (typeof PHONE_SOURCE_GROUPS)[number];

// Mirrors backend app/models/telephony_settings.py's ZEON_AUTH_MODES.
export const ZEON_AUTH_MODES = [
  { value: "bearer", label: "Bearer (только https)" },
  { value: "hash", label: "Hash (md5-подпись)" },
] as const;
export type ZeonAuthMode = (typeof ZEON_AUTH_MODES)[number]["value"];

// Mirrors backend app/models/telephony_settings.py's ZEON_AUDIO_METHODS.
export const ZEON_AUDIO_METHODS = [
  { value: "get-mp3", label: "get-mp3 (сжатая запись)" },
  { value: "get-file", label: "get-file (исходный файл)" },
] as const;
export type ZeonAudioMethod = (typeof ZEON_AUDIO_METHODS)[number]["value"];
