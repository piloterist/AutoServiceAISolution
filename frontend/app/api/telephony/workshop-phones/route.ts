// Proxies the "Цех — Телефон — Добавочный" directory list/create -
// Settings -> IP-телефония. See app/api/telephony/sources/route.ts for the
// same shape (phone_sources' own, unrelated directory).
import { NextRequest, NextResponse } from "next/server";

import {
  createWorkshopPhoneMapping,
  getWorkshopPhoneMappings,
  type WorkshopPhoneMappingWrite,
} from "@/lib/backend-api";

export async function GET() {
  try {
    return NextResponse.json(await getWorkshopPhoneMappings());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function POST(request: NextRequest) {
  const body = (await request.json()) as WorkshopPhoneMappingWrite;

  try {
    return NextResponse.json(await createWorkshopPhoneMapping(body), { status: 201 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("422") ? 422 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}
