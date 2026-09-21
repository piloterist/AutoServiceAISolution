// Proxies the ЗН autocomplete dropdown both Planner dialogs share - see
// app/api/admin/[resource]/route.ts for the general bridge-route rationale.
import { NextRequest, NextResponse } from "next/server";

import { searchPlannerWorkOrders } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams.get("q") ?? "";
  try {
    return NextResponse.json(await searchPlannerWorkOrders(q));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
