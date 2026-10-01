"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { monthRange } from "@/lib/period";
import { readPeriodOverride } from "@/lib/period-override";

/** Seeds the dashboard's own date_from/date_to filter from Cockpit's
 * persisted month override (see lib/period-override.ts) - per product ask,
 * 2026-10-01: "выбранный месяц автоматически встает в фильтре на листе
 * Аналитика и стоит там сколько бы лист Аналитика не открывали". Renders
 * nothing; its only job is the redirect-on-mount below.
 *
 * A no-op whenever the URL already carries an explicit date_from - either
 * the operator (or DashboardFilters' own submit, see that component) just
 * set one by hand this visit, or this redirect itself already ran once for
 * this page load. That's also how a manual filter change "wins" for the
 * rest of that visit without this effect fighting it. */
export function DashboardPeriodSync({ userId }: { userId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (searchParams.get("date_from")) return;
    const override = readPeriodOverride(userId);
    if (!override) return;
    const { dateFrom, dateTo } = monthRange(override.year, override.month);
    const next = new URLSearchParams(searchParams.toString());
    next.set("date_from", dateFrom);
    next.set("date_to", dateTo);
    router.replace(`${pathname}?${next.toString()}`);
    // Only on mount - this must not re-fire just because the operator
    // cleared the date filter afterward (reading `searchParams` inside the
    // effect without listing it as a dep is deliberate here).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
