// История заездов бокса по дням: фото въезда/выезда, время в боксе, привязанный ЗН.
import { NextRequest, NextResponse } from "next/server";

import { getBayHistory } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const dateFrom = params.get("date_from");
  const dateTo = params.get("date_to");
  const jobId = params.get("job_id");
  if (!jobId && (!dateFrom || !dateTo)) {
    return NextResponse.json({ error: "date_from и date_to обязательны" }, { status: 400 });
  }
  try {
    return NextResponse.json(
      await getBayHistory({
        date_from: dateFrom ?? undefined,
        date_to: dateTo ?? undefined,
        job_id: jobId ?? undefined,
        bay_id: params.get("bay_id") ?? undefined,
        workshop_id: params.get("workshop_id") ?? undefined,
      }),
    );
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
