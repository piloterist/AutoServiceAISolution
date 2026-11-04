// Ручное событие бокса (въезд/выезд/коррекция) - доступно любой роли с вкладкой «Боксы».
import { NextRequest, NextResponse } from "next/server";

import { createBayEvent } from "@/lib/backend-api";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await request.json();
  try {
    return NextResponse.json(await createBayEvent(id, { ...body, source: "manual" }));
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
