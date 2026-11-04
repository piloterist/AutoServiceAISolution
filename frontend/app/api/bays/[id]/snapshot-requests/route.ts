// Кнопка «Получить кадр»: создаёт запрос, который заберёт узел на площадке.
import { NextRequest, NextResponse } from "next/server";

import { requestBaySnapshot } from "@/lib/backend-api";

export async function POST(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    return NextResponse.json(await requestBaySnapshot(id));
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
