// Proxies the "Получить ЗН" plate lookup both Planner dialogs offer as a
// fallback when the usual ЗН autocomplete finds nothing (today's own order,
// not yet reached by the once-daily 1C export) - see
// backend/app/services/fivesystems_client.py's module docstring for the
// full why/how, and app/api/admin/[resource]/route.ts for the general
// bridge-route rationale.
import { NextRequest, NextResponse } from "next/server";

import { lookupPlannerWorkOrderByPlate } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const plate = request.nextUrl.searchParams.get("plate") ?? "";
  if (!plate.trim()) {
    return NextResponse.json({ error: "plate is required" }, { status: 422 });
  }
  try {
    return NextResponse.json(await lookupPlannerWorkOrderByPlate(plate));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("404") ? 404 : message.includes("503") ? 503 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}
