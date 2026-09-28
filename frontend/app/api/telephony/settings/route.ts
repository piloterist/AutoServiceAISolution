// Proxies Settings -> IP-телефония's connection form - same bridge role as
// app/api/settings/route.ts, see that file's comment.
import { NextRequest, NextResponse } from "next/server";

import { getTelephonySettings, type TelephonySettingsWrite, updateTelephonySettings } from "@/lib/backend-api";

export async function GET() {
  try {
    return NextResponse.json(await getTelephonySettings());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function PUT(request: NextRequest) {
  const body = (await request.json()) as TelephonySettingsWrite;

  try {
    return NextResponse.json(await updateTelephonySettings(body));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("422") ? 422 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}
