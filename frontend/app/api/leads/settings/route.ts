// Proxies Settings -> Заявки's connection form - same bridge role as
// app/api/telephony/settings/route.ts, see that file's comment.
import { NextRequest, NextResponse } from "next/server";

import { getLeadsSettings, type LeadsSettingsWrite, updateLeadsSettings } from "@/lib/backend-api";

export async function GET() {
  try {
    return NextResponse.json(await getLeadsSettings());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function PUT(request: NextRequest) {
  const body = (await request.json()) as LeadsSettingsWrite;

  try {
    return NextResponse.json(await updateLeadsSettings(body));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("422") ? 422 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}
