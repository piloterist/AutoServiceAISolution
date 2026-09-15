// Date-range helpers for the dashboard's "period" + "previous period"
// comparison. Pure functions (no server-only import) - used from the
// dashboard's Server Component. Dates are plain "YYYY-MM-DD" strings,
// always parsed/formatted in UTC (matching how a date-only string parses -
// see backend-api.ts's dateToParam - so this never depends on the server
// container's local timezone).

function toUTCDate(value: string): Date {
  return new Date(`${value}T00:00:00Z`);
}

function fmt(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** The dashboard's default view when no period filter is set - the current
 * calendar month, per the operator's own stated preference. */
export function currentMonthRange(): { dateFrom: string; dateTo: string } {
  const now = new Date();
  const year = now.getUTCFullYear();
  const month = now.getUTCMonth();
  return {
    dateFrom: fmt(new Date(Date.UTC(year, month, 1))),
    dateTo: fmt(new Date(Date.UTC(year, month + 1, 0))),
  };
}

function isFirstOfMonth(d: Date): boolean {
  return d.getUTCDate() === 1;
}

function isLastOfMonth(d: Date): boolean {
  const next = new Date(d.getTime());
  next.setUTCDate(next.getUTCDate() + 1);
  return next.getUTCDate() === 1;
}

function monthsBetweenInclusive(from: Date, to: Date): number {
  return (to.getUTCFullYear() - from.getUTCFullYear()) * 12 + (to.getUTCMonth() - from.getUTCMonth()) + 1;
}

/** The period immediately preceding the given one, same length.
 *
 * When the selected range is exactly N whole calendar months (the common
 * case: the default current-month view, or a month/quarter/year picked via
 * the date filter), the previous period is also N whole calendar months -
 * so "1 month" compares against the previous calendar month, "2 months"
 * against the 2 calendar months before that, and a full year against the
 * previous full year - matching how the business actually thinks about
 * period-over-period, not just "N days back". For an arbitrary custom range
 * (not calendar-month-aligned), it falls back to shifting the whole window
 * back by its own length.
 */
export function previousPeriod(dateFrom: string, dateTo: string): { dateFrom: string; dateTo: string } {
  const from = toUTCDate(dateFrom);
  const to = toUTCDate(dateTo);

  if (isFirstOfMonth(from) && isLastOfMonth(to)) {
    const monthCount = monthsBetweenInclusive(from, to);
    // Date.UTC(y, m, 0) is the last day of month (m - 1) - i.e. the day
    // right before `from`.
    const prevTo = new Date(Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), 0));
    const prevFrom = new Date(
      Date.UTC(prevTo.getUTCFullYear(), prevTo.getUTCMonth() - (monthCount - 1), 1),
    );
    return { dateFrom: fmt(prevFrom), dateTo: fmt(prevTo) };
  }

  const durationMs = to.getTime() - from.getTime();
  const prevTo = new Date(from.getTime() - 24 * 60 * 60 * 1000);
  const prevFrom = new Date(prevTo.getTime() - durationMs);
  return { dateFrom: fmt(prevFrom), dateTo: fmt(prevTo) };
}
