// "Проверить соединение" button - see app/api/telephony/settings/route.ts.
import { NextResponse } from "next/server";

import { pingTelephony } from "@/lib/backend-api";

export async function POST() {
  try {
    return NextResponse.json(await pingTelephony());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
