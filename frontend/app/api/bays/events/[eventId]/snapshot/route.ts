// Снимок въезда/выезда в момент распознавания номера - через наш бэкенд (Яндекс.Диск).
import { NextResponse } from "next/server";

import { fetchBayEventSnapshot } from "@/lib/backend-api";

export async function GET(_request: Request, { params }: { params: Promise<{ eventId: string }> }) {
  const { eventId } = await params;
  const image = await fetchBayEventSnapshot(eventId);
  if (!image) return NextResponse.json({ error: "Snapshot not found" }, { status: 404 });
  return new NextResponse(image.body, {
    headers: { "Content-Type": image.contentType, "Cache-Control": "private, max-age=86400" },
  });
}
