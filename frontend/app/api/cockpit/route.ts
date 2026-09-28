// Proxies the Cockpit snapshot to the browser - see lib/backend-api.ts's
// module comment for why this bridge exists (BACKEND_API_TOKEN never
// reaches the client).
import { NextRequest, NextResponse } from "next/server";

import { getCockpitSnapshot } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const workshopId = searchParams.get("workshop_id") ?? undefined;
  const includeNzp = searchParams.get("include_nzp") === "true";

  try {
    return NextResponse.json(await getCockpitSnapshot({ workshopId, includeNzp }));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
