// Ворота кузовного цеха: машины в цехе / история заездов (GET) и ручной въезд (POST) -
// доступно любой роли с вкладкой «Боксы» (см. middleware.ts).
import { NextRequest, NextResponse } from "next/server";

import { createGateStay, getGateStays } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const workshopId = params.get("workshop_id");
  if (!workshopId) {
    return NextResponse.json({ error: "workshop_id обязателен" }, { status: 400 });
  }
  try {
    return NextResponse.json(
      await getGateStays({
        workshop_id: workshopId,
        status: params.get("status") === "all" ? "all" : "inside",
        date_from: params.get("date_from") ?? undefined,
        date_to: params.get("date_to") ?? undefined,
      }),
    );
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}

export async function POST(request: NextRequest) {
  try {
    return NextResponse.json(await createGateStay(await request.json()), { status: 201 });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
