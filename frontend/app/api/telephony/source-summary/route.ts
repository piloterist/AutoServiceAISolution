// Feeds the /telephony stats page's "Итог по каждому источнику" table -
// open to any authenticated user whose role has the /telephony tab (see
// middleware.ts), unlike the rest of app/api/telephony/*, which is
// Admin-only (Settings -> IP-телефония).
import { NextRequest, NextResponse } from "next/server";

import { getSourceSummary } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const startDate = searchParams.get("start_date") ?? undefined;
  const endDate = searchParams.get("end_date") ?? undefined;

  try {
    return NextResponse.json(await getSourceSummary({ startDate, endDate }));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
