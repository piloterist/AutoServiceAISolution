import type { CrmTaskStatus } from "@/lib/backend-api";

export type Column = {
  key: CrmTaskStatus;
  title: string;
  icon: string;
  /** Moving a card here by hand opens a dialog asking for a mandatory reason. */
  needsReason?: boolean;
};

export const COLUMNS: Column[] = [
  { key: "control", title: "На контроле", icon: "👁️" },
  { key: "inspection", title: "Записан на осмотр", icon: "📅" },
  { key: "thinking", title: "Думает", icon: "💭" },
  { key: "refused", title: "Отказ", icon: "✖️", needsReason: true },
  { key: "work_order", title: "Заказ-наряд", icon: "✅" },
];

/** By hand: to «Отказ» from any column; back to «На контроле» from «Отказ» and from «Записан на
 * осмотр» (that deletes the planner record); from «На контроле» to «Записан на осмотр» (a dialog
 * creates the planner record). Every other column is reached by itself (repair request -> work
 * order). The backend enforces the same rule. */
export function canMoveByHand(from: CrmTaskStatus, to: CrmTaskStatus): boolean {
  if (from === to) return false;
  if (to === "refused") return true;
  if (to === "control") return from === "refused" || from === "inspection";
  return to === "inspection" && from === "control";
}

/** "16.11.2026" or "16.11.2026 - 18.11.2026" from the planner's date-only inspection stage. */
export function formatInspection(start: string | null, end: string | null): string | null {
  if (!start) return null;
  const fmt = (value: string) => value.split("-").reverse().join(".");
  return end && end !== start ? `${fmt(start)} - ${fmt(end)}` : fmt(start);
}

export function columnOf(status: CrmTaskStatus): Column {
  return COLUMNS.find((column) => column.key === status) ?? COLUMNS[0];
}

// "9001234567" -> "+7 900 123-45-67"
export function formatPhone(phone: string): string {
  if (phone.length === 10) {
    return `+7 ${phone.slice(0, 3)} ${phone.slice(3, 6)}-${phone.slice(6, 8)}-${phone.slice(8, 10)}`;
  }
  return phone;
}

/** "2026-11-17" -> "17.11.2026" */
export function formatDate(value: string): string {
  return value.split("-").reverse().join(".");
}

export function formatMoment(iso: string, withYear = false): string {
  return new Date(iso).toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    ...(withYear ? { year: "numeric" } : {}),
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Откуда карточка: звонок, заявка с сайта или создана руками (телефон нигде не найден). */
export function sourceTitle(source: "call" | "lead" | "manual"): string {
  return source === "lead" ? "Заявка с сайта" : source === "manual" ? "Создана вручную" : "Звонок";
}
