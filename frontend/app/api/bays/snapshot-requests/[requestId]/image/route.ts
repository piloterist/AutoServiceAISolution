// Полученный по кнопке кадр бокса - картинка через наш бэкенд (Яндекс.Диск).
import { NextResponse } from "next/server";

import { fetchBaySnapshotRequestImage } from "@/lib/backend-api";

export async function GET(_request: Request, { params }: { params: Promise<{ requestId: string }> }) {
  const { requestId } = await params;
  const image = await fetchBaySnapshotRequestImage(requestId);
  if (!image) return NextResponse.json({ error: "Snapshot not found" }, { status: 404 });
  return new NextResponse(image.body, {
    headers: { "Content-Type": image.contentType, "Cache-Control": "no-store" },
  });
}
