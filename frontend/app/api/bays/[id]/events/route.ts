// Ручное событие бокса (въезд/выезд/коррекция) - доступно любой роли с вкладкой «Боксы».
import { NextRequest, NextResponse } from "next/server";

import { createBayEvent } from "@/lib/backend-api";
import { getCurrentUser } from "@/lib/session";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await request.json();
  const user = await getCurrentUser();
  try {
    return NextResponse.json(
      await createBayEvent(
        id,
        { ...body, source: "manual" },
        user ? { id: user.id, fullName: user.fullName } : undefined,
      ),
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: message.includes("422") ? 422 : 502 });
  }
}
