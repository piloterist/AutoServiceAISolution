// Proxies the phone-source directory list/create - Settings -> IP-телефония
// -> Источники. See app/api/telephony/settings/route.ts for the bridge role.
import { NextRequest, NextResponse } from "next/server";

import { createPhoneSource, getPhoneSources, type PhoneSourceWrite } from "@/lib/backend-api";

export async function GET() {
  try {
    return NextResponse.json(await getPhoneSources());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function POST(request: NextRequest) {
  const body = (await request.json()) as PhoneSourceWrite;

  try {
    return NextResponse.json(await createPhoneSource(body), { status: 201 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("409") ? 409 : message.includes("422") ? 422 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}
