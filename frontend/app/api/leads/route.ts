// Full lead history (/leads page) - open to any authenticated user, same
// scope as app/api/telephony/source-summary/route.ts (not under
// /settings/import/ping/etc, so middleware.ts's admin gate doesn't catch it).
import { NextResponse } from "next/server";

import { getLeads } from "@/lib/backend-api";

export async function GET() {
  try {
    return NextResponse.json(await getLeads());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
