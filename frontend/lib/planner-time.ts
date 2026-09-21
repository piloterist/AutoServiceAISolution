// Date/time helpers shared by the Слесарный and Кузовной Planner views.
// Dates are plain "YYYY-MM-DD" strings throughout (never Date objects held
// in state) so day-arithmetic stays unambiguous local-calendar arithmetic,
// not UTC-vs-local Date parsing footguns.

const WEEKDAY_SHORT = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
const WEEKDAY_LONG = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];
const MONTH_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const MONTH_GENITIVE = [
  "января",
  "февраля",
  "марта",
  "апреля",
  "мая",
  "июня",
  "июля",
  "августа",
  "сентября",
  "октября",
  "ноября",
  "декабря",
];

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

export function toIso(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Parses "YYYY-MM-DD" as a LOCAL date (midnight local time) - `new
 * Date("YYYY-MM-DD")` parses as UTC midnight instead, which shifts a day
 * backwards in any timezone behind UTC. */
export function parseIso(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function todayIso(): string {
  return toIso(new Date());
}

export function addDaysIso(iso: string, days: number): string {
  const d = parseIso(iso);
  d.setDate(d.getDate() + days);
  return toIso(d);
}

/** Monday=0 .. Sunday=6, matching backend Workshop.working_days (Python's
 * date.weekday()) - JS's own Date.getDay() is Sunday=0, so this remaps it. */
export function isoWeekday(iso: string): number {
  const jsDay = parseIso(iso).getDay(); // 0=Sun..6=Sat
  return (jsDay + 6) % 7;
}

export function isWorkingDay(iso: string, workingDays: number[]): boolean {
  return workingDays.includes(isoWeekday(iso));
}

/** "Пн 21 сен" - day-column headers. */
export function formatShortDay(iso: string): string {
  const d = parseIso(iso);
  return `${WEEKDAY_SHORT[d.getDay()]} ${d.getDate()} ${MONTH_SHORT[d.getMonth()]}`;
}

/** "Понедельник, 21 сентября" - the big day header above the Слесарный grid. */
export function formatLongDay(iso: string): string {
  const d = parseIso(iso);
  const weekday = WEEKDAY_LONG[d.getDay()];
  return `${weekday.charAt(0).toUpperCase()}${weekday.slice(1)}, ${d.getDate()} ${MONTH_GENITIVE[d.getMonth()]}`;
}

/** "21.09" - Кузовной's "Заезд .. Выезд .." and per-row date ranges. */
export function formatShortDate(iso: string): string {
  const d = parseIso(iso);
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}`;
}

export function timeToMinutes(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

export function minutesToTime(minutes: number): string {
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
}

/** Rounds to the nearest 30-minute mark - every Слесарный time field snaps
 * to this grid (product brief: "с интервалом 30 минут"). */
export function roundToSlot(minutes: number, slot = 30): number {
  return Math.round(minutes / slot) * slot;
}

export function diffDaysIso(a: string, b: string): number {
  return Math.round((parseIso(b).getTime() - parseIso(a).getTime()) / 86_400_000);
}
