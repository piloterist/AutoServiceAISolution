// Последний кадр пустого бокса (узел снимает его раз в минуту после 10 минут простоя).
import { NextResponse } from "next/server";

import { fetchBayLatestFrame } from "@/lib/backend-api";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const image = await fetchBayLatestFrame(id);
  if (!image) return NextResponse.json({ error: "Frame not found" }, { status: 404 });
  return new NextResponse(image.body, {
    headers: { "Content-Type": image.contentType, "Cache-Control": "no-store" },
  });
}
