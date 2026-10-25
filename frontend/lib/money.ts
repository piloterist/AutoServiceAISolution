// Money/date helpers for the Касса page.

const NBSP = " ";

/** 138409.55 -> "138 409,55" (thousand separators, always two decimals). */
export function formatMoney(value: number | string): string {
  const number = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(number)) return "0,00";
  return number.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Live formatting of an amount field while typing: digits grouped by
 * thousands, a comma or dot starts the (at most two-digit) fraction, and
 * everything else is dropped - "1234567,8" -> "1 234 567,8". */
export function formatMoneyInput(raw: string): string {
  const cleaned = raw.replace(/[^\d.,]/g, "");
  const separatorAt = cleaned.search(/[.,]/);
  const integerPart = (separatorAt === -1 ? cleaned : cleaned.slice(0, separatorAt)).replace(/\D/g, "");
  const grouped = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  if (separatorAt === -1) return grouped;
  const fraction = cleaned.slice(separatorAt + 1).replace(/\D/g, "").slice(0, 2);
  return `${grouped || "0"},${fraction}`;
}

/** The field's text -> a number ("1 234,50" -> 1234.5); null if empty. */
export function parseMoney(text: string): number | null {
  const normalized = text.replace(/[\s ]/g, "").replace(",", ".");
  if (normalized === "") return null;
  const number = Number(normalized);
  return Number.isFinite(number) ? number : null;
}

/** On leaving the field: always show kopeks ("1 234" -> "1 234,00"). */
export function padMoneyInput(text: string): string {
  const number = parseMoney(text);
  return number === null ? "" : formatMoney(number).replace(new RegExp(NBSP, "g"), " ");
}

/** Today's date in Moscow, "YYYY-MM-DD" - the cash book's own "today". */
export function todayMsk(): string {
  return new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

/** "2026-10-24" -> "24.10.2026". */
export function formatDay(iso: string): string {
  const [year, month, day] = iso.split("-");
  return `${day}.${month}.${year}`;
}

/** "2026-10-24T11:05:00+00:00" -> "24.10.2026 14:05" (Moscow). */
export function formatMoment(iso: string): string {
  const moscow = new Date(new Date(iso).getTime() + 3 * 60 * 60 * 1000).toISOString();
  return `${formatDay(moscow.slice(0, 10))} ${moscow.slice(11, 16)}`;
}
