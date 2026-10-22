// "Показать историю звонков" on the Телефония page - same auth scope as
// app/api/telephony/source-summary/calls/route.ts (any authenticated user
// with the /telephony tab).
import { NextRequest, NextResponse } from "next/server";

import { getClientCallHistory } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const phone = new URL(request.url).searchParams.get("phone");
  if (!phone) return NextResponse.json({ error: "phone is required" }, { status: 400 });

  try {
    return NextResponse.json(await getClientCallHistory(phone));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
