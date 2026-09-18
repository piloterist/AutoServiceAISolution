// Proxies the work orders list to the browser - WorkOrdersTable and
// WorkOrdersPrefetcher are client components and can't import
// lib/backend-api.ts directly (it's server-only), so this route handler is
// the bridge: it runs server-side, holds BACKEND_API_TOKEN, and the browser
// only ever talks to this same-origin route (gated by middleware.ts like
// every other page/route here). Same pattern as app/api/settings/route.ts.
import { NextRequest, NextResponse } from "next/server";

import { getWorkOrders } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;

  try {
    const data = await getWorkOrders({
      paidFrom: params.get("paid_from") || undefined,
      paidTo: params.get("paid_to") || undefined,
      limit: params.get("limit") ? Number(params.get("limit")) : undefined,
      offset: params.get("offset") ? Number(params.get("offset")) : undefined,
    });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
