// Browser-side cache for the (unfiltered) work orders list, shared between
// WorkOrdersPrefetcher (mounted on the dashboard, starts loading in the
// background while the operator is looking at the dashboard) and
// WorkOrdersTable (renders from this cache instantly if it's already there
// by the time the operator navigates to /work-orders). Not imported by any
// Server Component - both callers are "use client".
import type { WorkOrderListItem } from "@/lib/backend-api";

const CACHE_KEY = "work-orders-cache:v1";
// Long enough to survive a normal dashboard-then-work-orders click, short
// enough that a stale list can't linger unnoticed for the rest of a long
// session after a new 1C export lands.
const CACHE_TTL_MS = 15 * 60 * 1000;
// Fetched in pages instead of one 50,000-row request - the same "don't do
// it all in one shot" reasoning as process_work_order_import's CHUNK_SIZE
// on the backend (see the 2026-09-17 incident): lets a caller render/cache
// the freshest rows as soon as they arrive instead of waiting on the whole
// list, and bounds each individual request.
const PAGE_SIZE = 10_000;

type CacheEntry = {
  items: WorkOrderListItem[];
  total: number;
  /** false while a page fetch is still in flight for this entry - a
   * caller shouldn't treat item.length < total as "capped", just "still
   * loading the rest". */
  complete: boolean;
  fetchedAt: number;
};

let memoryCache: CacheEntry | null = null;
let inFlight: Promise<CacheEntry> | null = null;

function isFresh(entry: CacheEntry): boolean {
  return Date.now() - entry.fetchedAt < CACHE_TTL_MS;
}

function readSessionCache(): CacheEntry | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    return raw ? (JSON.parse(raw) as CacheEntry) : null;
  } catch {
    return null;
  }
}

function writeSessionCache(entry: CacheEntry): void {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(entry));
  } catch {
    // sessionStorage can throw (private browsing, quota exceeded) - the
    // in-memory cache still covers this tab for the rest of its lifetime,
    // so a failed write here is safe to ignore.
  }
}

/** Whatever's cached right now (possibly still loading - see `complete`),
 * or null if there's nothing fresh. Synchronous, safe to call on render. */
export function getCachedWorkOrders(): CacheEntry | null {
  if (memoryCache && isFresh(memoryCache)) return memoryCache;
  const fromSession = readSessionCache();
  if (fromSession && isFresh(fromSession)) {
    memoryCache = fromSession;
    return fromSession;
  }
  return null;
}

/** Fetches work orders page by page, newest to oldest (the backend already
 * orders by document_date desc - see work_order_query_service.
 * list_work_orders), until it has all of them - no fixed cap, so this can
 * never silently truncate the list the way a single hardcoded `limit` once
 * did (see the 2026-09-17 5000-row truncation fix). Calls onProgress after
 * every page. */
async function fetchAllWorkOrders(
  params: { paidFrom?: string; paidTo?: string },
  onProgress?: (items: WorkOrderListItem[], total: number) => void,
): Promise<{ items: WorkOrderListItem[]; total: number }> {
  let items: WorkOrderListItem[] = [];
  let total = 0;
  let offset = 0;

  for (;;) {
    const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (params.paidFrom) query.set("paid_from", params.paidFrom);
    if (params.paidTo) query.set("paid_to", params.paidTo);

    const res = await fetch(`/api/work-orders?${query.toString()}`);
    if (!res.ok) throw new Error(`Не удалось загрузить заказ-наряды (${res.status})`);
    const page = (await res.json()) as { items: WorkOrderListItem[]; total: number };

    items = items.concat(page.items);
    total = page.total;
    onProgress?.(items, total);

    offset += page.items.length;
    if (page.items.length === 0 || offset >= total) break;
  }

  return { items, total };
}

/** The cached/prefetchable path - unfiltered list only (no paid_from/
 * paid_to). That's the one navigated to over and over (dashboard -> work
 * orders), so it's the one worth caching; a paid_from/paid_to click-through
 * from a dashboard tile is a one-off and always fetches fresh (see
 * loadWorkOrdersFiltered). Concurrent callers (the prefetcher and the work
 * orders page itself, if the operator navigates before the prefetch
 * finishes) share the same in-flight request instead of racing duplicate
 * fetches. */
export function loadWorkOrdersCached(
  onProgress?: (items: WorkOrderListItem[], total: number) => void,
): Promise<CacheEntry> {
  const cached = getCachedWorkOrders();
  if (cached?.complete) {
    onProgress?.(cached.items, cached.total);
    return Promise.resolve(cached);
  }

  if (inFlight) return inFlight;

  inFlight = fetchAllWorkOrders({}, onProgress)
    .then(({ items, total }) => {
      const entry: CacheEntry = { items, total, complete: true, fetchedAt: Date.now() };
      memoryCache = entry;
      writeSessionCache(entry);
      return entry;
    })
    .finally(() => {
      inFlight = null;
    });

  return inFlight;
}

/** Always fetches fresh - see loadWorkOrdersCached's doc comment for why
 * a paid_from/paid_to view doesn't go through the cache. */
export function loadWorkOrdersFiltered(
  params: { paidFrom?: string; paidTo?: string },
  onProgress?: (items: WorkOrderListItem[], total: number) => void,
): Promise<{ items: WorkOrderListItem[]; total: number }> {
  return fetchAllWorkOrders(params, onProgress);
}
