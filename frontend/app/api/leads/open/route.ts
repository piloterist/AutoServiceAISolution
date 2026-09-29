// Planner's envelope badge - same scope note as
// app/api/telephony/missed-calls/route.ts: deliberately not under
// /settings, so a Мастер приёмщик with only the Planner tab still sees it
// even without the full /leads tab.
import { NextResponse } from "next/server";

import { getOpenLeads } from "@/lib/backend-api";

export async function GET() {
  try {
    return NextResponse.json(await getOpenLeads());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
