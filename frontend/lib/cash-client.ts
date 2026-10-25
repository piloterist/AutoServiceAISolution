"use client";

// Client-side fetch wrappers for the Касса page, talking to the proxy routes
// under app/api/cash/* (the client-safe counterpart to the server-only
// functions in lib/backend-api.ts - types are reused via `import type`).
import type {
  CashBook,
  CashEntry,
  CashEntryWrite,
  CashSearchHit,
  CashWorkOrder,
  AuditLogEntry,
} from "@/lib/backend-api";

async function proxyFetch<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, { cache: "no-store", ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(typeof body.error === "string" ? body.error : `Ошибка запроса: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const jsonHeaders = { "Content-Type": "application/json" };

export function getCashBookClient(params: {
  workshopId: string;
  dateFrom: string;
  dateTo: string;
}): Promise<CashBook> {
  const query = new URLSearchParams({
    workshop_id: params.workshopId,
    date_from: params.dateFrom,
    date_to: params.dateTo,
  });
  return proxyFetch<CashBook>(`/api/cash/book?${query}`);
}

/** Entries of the desk by work-order number, earliest first. */
export function searchCashEntriesClient(workshopId: string, q: string): Promise<CashSearchHit[]> {
  const query = new URLSearchParams({ workshop_id: workshopId, q });
  return proxyFetch<CashSearchHit[]>(`/api/cash/search?${query}`);
}

export function searchCashWorkOrdersClient(workshopId: string, q: string): Promise<CashWorkOrder[]> {
  const query = new URLSearchParams({ workshop_id: workshopId, q });
  return proxyFetch<CashWorkOrder[]>(`/api/cash/work-orders?${query}`);
}

export function createCashEntryClient(payload: CashEntryWrite): Promise<CashEntry> {
  return proxyFetch<CashEntry>("/api/cash/entries", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

/** Edits an entry; an amount of 0 deletes it (`deleted: true`). */
export function updateCashEntryClient(
  id: string,
  payload: CashEntryWrite,
): Promise<{ deleted: boolean; entry: CashEntry | null }> {
  return proxyFetch(`/api/cash/entries/${id}`, {
    method: "PUT",
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
}

/** The change log of one cash entry. Goes through the Settings (Admin-only)
 * route: anyone else gets an error and the caller simply shows nothing. */
export function getCashEntryHistoryClient(entryId: string): Promise<AuditLogEntry[]> {
  const query = new URLSearchParams({ entity_type: "cash_entry", entity_id: entryId });
  return proxyFetch<AuditLogEntry[]>(`/api/admin/audit-log?${query}`);
}
