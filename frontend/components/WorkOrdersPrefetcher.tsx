"use client";

import { useEffect } from "react";

import { loadWorkOrdersCached } from "@/lib/work-orders-cache";

/** Invisible - mounted on the dashboard so the work orders list starts
 * loading into the shared cache (see lib/work-orders-cache.ts) while the
 * operator is looking at the dashboard, which they typically do for a
 * while right after opening it. Navigating to Work Orders afterwards then
 * renders from cache instantly instead of waiting on a fresh
 * multi-thousand-row fetch. */
export function WorkOrdersPrefetcher() {
  useEffect(() => {
    loadWorkOrdersCached().catch(() => {
      // Best-effort - a failed prefetch just means the work orders page
      // falls back to its own normal fetch, same as before this existed.
    });
  }, []);

  return null;
}
