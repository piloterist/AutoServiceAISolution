// The work orders counted in a conversion donut's "Заказ-нарядов" figure -
// the work-order list (a client component) filters itself down to these ids.
// Same auth scope as the other /api/telephony/* read routes.
import { NextRequest, NextResponse } from "next/server";

import { getConversionWorkOrderIds } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const kind = searchParams.get("kind") === "existing" ? "existing" : "new";
  const startDate = searchParams.get("start_date");
  const endDate = searchParams.get("end_date");
  if (!startDate || !endDate) {
    return NextResponse.json({ error: "start_date and end_date are required" }, { status: 400 });
  }
  const departments = (searchParams.get("departments") ?? "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);

  try {
    return NextResponse.json(
      await getConversionWorkOrderIds({ kind, startDate, endDate, departments }),
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
