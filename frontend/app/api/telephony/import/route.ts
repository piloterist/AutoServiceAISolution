// "Импортировать сейчас" button - see app/api/telephony/settings/route.ts.
import { NextRequest, NextResponse } from "next/server";

import { triggerTelephonyImport } from "@/lib/backend-api";

export async function POST(request: NextRequest) {
  const body = (await request.json().catch(() => ({}))) as { startDate?: string; endDate?: string };

  try {
    const range = body.startDate && body.endDate ? { startDate: body.startDate, endDate: body.endDate } : undefined;
    return NextResponse.json(await triggerTelephonyImport(range));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
