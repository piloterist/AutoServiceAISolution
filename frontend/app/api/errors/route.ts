// Лист «Ошибки»: список ошибок видеоконтроля (машина в боксе без заказ-наряда).
import { NextRequest, NextResponse } from "next/server";

import { getBayIssues } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const raw = request.nextUrl.searchParams.get("status");
  const status = raw === "open" || raw === "resolved" ? raw : "all";
  try {
    return NextResponse.json(await getBayIssues(status));
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
