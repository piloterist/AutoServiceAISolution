// Боксы: список боксов цеха с текущим состоянием (GET) и создание бокса (POST,
// только Админ - см. middleware.ts).
import { NextRequest, NextResponse } from "next/server";

import { createBay, getBays } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  try {
    return NextResponse.json(await getBays(request.nextUrl.searchParams.get("workshop_id") ?? undefined));
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}

export async function POST(request: NextRequest) {
  try {
    return NextResponse.json(await createBay(await request.json()));
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
