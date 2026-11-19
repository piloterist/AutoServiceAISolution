// Поправить номер/описание заезда у ворот; бэкенд заново ищет запись кузовного планировщика.
import { NextRequest, NextResponse } from "next/server";

import { updateGateStay } from "@/lib/backend-api";

export async function PATCH(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    return NextResponse.json(await updateGateStay(id, await request.json()));
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
