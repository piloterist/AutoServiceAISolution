"use client";

import { useEffect } from "react";

import { clearReceivablesFilters } from "@/lib/receivables-filters";

/** Rendered on the login page: reaching it means the user just logged out
 * (manually or via the daily auto-logout) or never logged in, so any
 * per-session remembered filters must not leak into the next login. */
export function ClearSessionFilters() {
  useEffect(() => {
    clearReceivablesFilters();
  }, []);
  return null;
}
