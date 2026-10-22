// Финансы -> Дебиторская задолженность filters survive navigating away and
// back (product ask, 2026-10-23: "запоминай и не сбрасывай пока не будет
// нажата кнопка Сбросить или не будет выполнен выход пользователя").
// sessionStorage, same choice/reasoning as WorkOrdersTable's own persisted
// filters: it must outlive a remount of the page, but only for this tab. The
// login page calls clearReceivablesFilters() on mount, so both a manual
// "Выйти" and the daily auto-logout (both land on /login) wipe it.

export type ReceivablesRepairScope = "all" | "insurance" | "current";

export type PersistedReceivablesFilters = {
  closedFrom: string;
  closedTo: string;
  onlyIndividualCustomer: boolean;
  repairScope: ReceivablesRepairScope;
};

const STORAGE_KEY = "receivables-filters:v1";

const SCOPES: ReceivablesRepairScope[] = ["all", "insurance", "current"];

export function readReceivablesFilters(): PersistedReceivablesFilters | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedReceivablesFilters>;
    return {
      closedFrom: typeof parsed.closedFrom === "string" ? parsed.closedFrom : "",
      closedTo: typeof parsed.closedTo === "string" ? parsed.closedTo : "",
      onlyIndividualCustomer: parsed.onlyIndividualCustomer === true,
      repairScope: SCOPES.includes(parsed.repairScope as ReceivablesRepairScope)
        ? (parsed.repairScope as ReceivablesRepairScope)
        : "all",
    };
  } catch {
    return null;
  }
}

export function writeReceivablesFilters(filters: PersistedReceivablesFilters): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
  } catch {
    // Ignore (private browsing, quota) - filters just won't survive a
    // remount this time.
  }
}

export function clearReceivablesFilters(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
