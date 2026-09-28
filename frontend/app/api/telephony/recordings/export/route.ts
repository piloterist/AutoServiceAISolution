// "Выгрузить и расшифровать" button - see app/api/telephony/settings/route.ts
// for the bridge role, and backend app/services/call_recording_service.py
// for what this actually triggers (runs in the background on the backend;
// this call just starts it).
import { NextRequest, NextResponse } from "next/server";

import { triggerCallRecordingExport } from "@/lib/backend-api";

export async function POST(request: NextRequest) {
  const body = (await request.json()) as { startDate: string; endDate: string };

  try {
    return NextResponse.json(await triggerCallRecordingExport(body));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
