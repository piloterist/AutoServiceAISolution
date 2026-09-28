// Planner's phone-icon badge - open to any authenticated user (not
// Admin-only), same scope as app/api/telephony/source-summary/route.ts:
// this path deliberately isn't under /settings, /sources, /ping, /import
// or /recordings, so middleware.ts's isTelephonyAdminApi check doesn't
// catch it - a Мастер приёмщик with only the Planner tab still needs to
// see this badge even without the full /telephony tab.
import { NextResponse } from "next/server";

import { getOpenMissedCalls } from "@/lib/backend-api";

export async function GET() {
  try {
    return NextResponse.json(await getOpenMissedCalls());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
