// Исправить номер заезда («Исправить номер» в истории): свой номер или «машина без номера».
import { NextRequest, NextResponse } from "next/server";

import { correctBayStayPlate } from "@/lib/backend-api";
import { getCurrentUser } from "@/lib/session";

export async function PATCH(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  const body = (await request.json().catch(() => ({}))) as { plate?: string | null; no_plate?: boolean };
  try {
    return NextResponse.json(
      await correctBayStayPlate(id, { plate: body.plate ?? null, no_plate: body.no_plate ?? false }, { id: user.id, fullName: user.fullName }),
    );
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
