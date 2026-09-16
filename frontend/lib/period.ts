// Date-range helpers for the dashboard's "period" + "previous period"
// comparison. Pure functions (no server-only import) - used from both the
// dashboard's Server Component (page.tsx) and the filter form's client
// component (DashboardFilters, for its previous-period auto-fill). Dates
// are plain "YYYY-MM-DD" strings, always parsed/formatted in UTC (matching
// how a date-only string parses - see backend-api.ts's dateToParam - so
// this never depends on the server container's local timezone).

function toUTCDate(value: string): Date {
  return new Date(`${value}T00:00:00Z`);
}

function fmt(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** The dashboard's default view when no period filter is set - month to
 * date (1st of the current month through today), not the full calendar
 * month - showing days that haven't happened yet as a flat empty tail on
 * the trend chart reads as broken, not "on track". */
export function monthToDateRange(): { dateFrom: string; dateTo: string } {
  const now = new Date();
  const year = now.getUTCFullYear();
  const month = now.getUTCMonth();
  return {
    dateFrom: fmt(new Date(Date.UTC(year, month, 1))),
    dateTo: fmt(now),
  };
}

/** Fixed window for the "заказ-нарядов по месяцам" chart - always January
 * of the current year through the current month, regardless of whatever
 * period is selected up top. A chart titled "by month" that only ever
 * shows the one selected month (or a handful of custom-range months) reads
 * as broken; this one is deliberately independent of the period filter. */
export function currentYearToDateRange(): { dateFrom: string; dateTo: string } {
  const now = new Date();
  const year = now.getUTCFullYear();
  const month = now.getUTCMonth();
  return {
    dateFrom: fmt(new Date(Date.UTC(year, 0, 1))),
    dateTo: fmt(new Date(Date.UTC(year, month + 1, 0))), // last day of the current month
  };
}

function monthsBetween(from: Date, to: Date): number {
  return (to.getUTCFullYear() - from.getUTCFullYear()) * 12 + (to.getUTCMonth() - from.getUTCMonth());
}

function shiftMonths(date: Date, months: number): Date {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() - months, date.getUTCDate()));
}

/** The period immediately preceding the given one, for a period-over-period
 * comparison - both endpoints shifted back by the same number of calendar
 * months, keeping the same day-of-month (so "01.09-15.09" compares against
 * "01.08-15.08", not some day-count-derived range that drifts off the
 * calendar grid).
 *
 * The shift is however many calendar months the selected range spans
 * (Aug-Sep = 1 month back, Jun-Sep = 3 months back), with a floor of 1 - a
 * range that doesn't cross a month boundary at all (the common case: the
 * default month-to-date view) still needs to compare against *some* other
 * period, so it falls back to "the previous calendar month" rather than
 * comparing a period against itself.
 */
export function previousPeriod(dateFrom: string, dateTo: string): { dateFrom: string; dateTo: string } {
  const from = toUTCDate(dateFrom);
  const to = toUTCDate(dateTo);
  const span = monthsBetween(from, to);
  const shift = span === 0 ? 1 : span;

  return {
    dateFrom: fmt(shiftMonths(from, shift)),
    dateTo: fmt(shiftMonths(to, shift)),
  };
}

/** Mirrors the backend's own auto-detection
 * (work_order_query_service._resolve_granularity) exactly, so it can be
 * computed once here and passed explicitly to every trend-shaped call
 * (revenue trend, payment trend, current period, previous period) - all of
 * them fetched in parallel, with no "wait for one response to know what to
 * ask the others for" dependency, and all guaranteed to bucket identically
 * so their series overlay on the same x-axis. */
export function resolveGranularity(dateFrom: string, dateTo: string): "day" | "week" | "month" {
  const from = toUTCDate(dateFrom);
  const to = toUTCDate(dateTo);
  // +1: the backend's own date_to is exclusive and gets pushed to the start
  // of the next day (see backend-api.ts's dateToParam) before this span is
  // measured there - this counts the same inclusive number of days.
  const inclusiveSpanDays = Math.round((to.getTime() - from.getTime()) / 86_400_000) + 1;
  if (inclusiveSpanDays <= 31) return "day";
  if (inclusiveSpanDays <= 92) return "week";
  return "month";
}
