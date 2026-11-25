// Proxies the work orders list to the browser - WorkOrdersTable and
// WorkOrdersPrefetcher are client components and can't import
// lib/backend-api.ts directly (it's server-only), so this route handler is
// the bridge: it runs server-side, holds BACKEND_API_TOKEN, and the browser
// only ever talks to this same-origin route (gated by middleware.ts like
// every other page/route here). Same pattern as app/api/settings/route.ts.
import { NextRequest, NextResponse } from "next/server";

import { getWorkOrders } from "@/lib/backend-api";
import { isBudgetRevenueKind } from "@/lib/budget-revenue";
import { getCurrentUser } from "@/lib/session";

function budgetRevenue(params: URLSearchParams) {
  const kind = params.get("budget_revenue");
  const year = Number(params.get("budget_year"));
  const month = Number(params.get("budget_month"));
  if (!isBudgetRevenueKind(kind) || !year || !month) return undefined;
  const yearTo = Number(params.get("budget_year_to")) || undefined;
  const monthTo = Number(params.get("budget_month_to")) || undefined;
  return { kind, year, month, yearTo, monthTo } as const;
}

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  // Requests with an overdue call are scoped to the caller's цех (the Planner bell's link).
  const user = await getCurrentUser();

  try {
    const data = await getWorkOrders({
      onlyRequestIssues: params.get("only_request_issues") === "true",
      actor: user ? { id: user.id, fullName: user.fullName } : undefined,
      paidFrom: params.get("paid_from") || undefined,
      paidTo: params.get("paid_to") || undefined,
      onlyReceivables: params.get("only_receivables") === "true",
      onlyRevenue: params.get("only_revenue") === "true",
      budgetRevenue: budgetRevenue(params),
      workshopId: params.get("workshop_id") || undefined,
      includeRequests: params.get("include_requests") === "true",
      limit: params.get("limit") ? Number(params.get("limit")) : undefined,
      offset: params.get("offset") ? Number(params.get("offset")) : undefined,
    });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
