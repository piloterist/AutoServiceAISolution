// Row-expand drill-down on "Итог по каждому источнику" - same auth scope
// as app/api/telephony/source-summary/route.ts (open to any authenticated
// user with the /telephony tab, not Admin-only).
import { NextRequest, NextResponse } from "next/server";

import { getLineCalls } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const lineCode = searchParams.get("line_code");
  if (!lineCode) return NextResponse.json({ error: "line_code is required" }, { status: 400 });

  const startDate = searchParams.get("start_date") ?? undefined;
  const endDate = searchParams.get("end_date") ?? undefined;

  try {
    return NextResponse.json(await getLineCalls({ lineCode, startDate, endDate }));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
