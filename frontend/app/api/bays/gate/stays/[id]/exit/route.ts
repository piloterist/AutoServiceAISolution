// Ручной выезд машины, которую камера у ворот не увидела.
import { NextRequest, NextResponse } from "next/server";

import { exitGateStay } from "@/lib/backend-api";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = (await request.json().catch(() => ({}))) as { exited_at?: string | null };
  try {
    return NextResponse.json(await exitGateStay(id, { exited_at: body.exited_at ?? null }));
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
