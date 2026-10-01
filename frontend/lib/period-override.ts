// Shared cross-page "selected month" override - Cockpit's own month/year
// picker (see components/cockpit/CockpitView.tsx) writes here whenever the
// operator picks a month other than the current one, and the Dashboard
// page reads it to seed its own period filter with the same month (per
// product ask, 2026-10-01: "выбранный месяц автоматически встает в
// фильтре на листе Аналитика и стоит там сколько бы лист Аналитика не
// открывали"). Cleared only by Cockpit's own reset lamp - see
// CockpitView's handleResetPeriod.
//
// localStorage (not sessionStorage) on purpose - this must survive
// closing/reopening the tab, unlike components/WorkOrdersTable.tsx's own
// sessionStorage-persisted filters (those are explicitly "this tab only").
// Per-user key, same model as CockpitView's own NZP_STORAGE_KEY_PREFIX -
// a shared machine/browser shouldn't leak one operator's selected month
// into another's view.
const STORAGE_KEY_PREFIX = "cockpit-period-override:";

export type PeriodOverride = { year: number; month: number };

function storageKey(userId: string): string {
  return `${STORAGE_KEY_PREFIX}${userId}`;
}

export function readPeriodOverride(userId: string): PeriodOverride | null {
  try {
    const raw = window.localStorage.getItem(storageKey(userId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PeriodOverride>;
    if (typeof parsed.year === "number" && typeof parsed.month === "number") {
      return { year: parsed.year, month: parsed.month };
    }
    return null;
  } catch {
    // Private browsing / blocked storage / corrupt value - fall back to
    // "no override" (current month), same degradation as everywhere else
    // this codebase touches localStorage.
    return null;
  }
}

export function writePeriodOverride(userId: string, value: PeriodOverride | null): void {
  try {
    if (value) {
      window.localStorage.setItem(storageKey(userId), JSON.stringify(value));
    } else {
      window.localStorage.removeItem(storageKey(userId));
    }
  } catch {
    // ignore - per-viewer convenience only
  }
}
