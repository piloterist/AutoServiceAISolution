// «Создать боксы по числу постов цеха» (только Админ - см. middleware.ts).
import { NextRequest, NextResponse } from "next/server";

import { createDefaultBays } from "@/lib/backend-api";

export async function POST(request: NextRequest) {
  const workshopId = request.nextUrl.searchParams.get("workshop_id");
  if (!workshopId) return NextResponse.json({ error: "workshop_id is required" }, { status: 400 });
  try {
    return NextResponse.json(await createDefaultBays(workshopId));
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
