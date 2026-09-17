// Proxies the Settings page's save action to the backend - a client
// component can't import lib/backend-api.ts directly (it's server-only,
// see that file's own comment), so this route handler is the bridge: it
// runs server-side, holds BACKEND_API_TOKEN, and the browser only ever
// talks to this same-origin route (gated by middleware.ts like every other
// page/route here).
import { NextRequest, NextResponse } from "next/server";

import { type AppSettings, updateAppSettings } from "@/lib/backend-api";

export async function PUT(request: NextRequest) {
  const body = (await request.json()) as AppSettings;

  try {
    const settings = await updateAppSettings(body);
    return NextResponse.json(settings);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
