// Телефония -> "Конверсия" - same auth scope as the other /api/telephony/*
// read routes (any authenticated user with the /telephony tab).
import { NextRequest, NextResponse } from "next/server";

import { getConversion } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const startDate = searchParams.get("start_date") ?? undefined;
  const endDate = searchParams.get("end_date") ?? undefined;
  const departments = (searchParams.get("departments") ?? "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);

  try {
    return NextResponse.json(
      await getConversion({
        startDate,
        endDate,
        departments,
        includeRequests: searchParams.get("include_requests") === "true",
      }),
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
