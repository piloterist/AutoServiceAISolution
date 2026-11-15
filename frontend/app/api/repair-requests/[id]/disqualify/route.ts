// Дисквалификация заявки (две попытки или право «без попыток» - проверяет бэкенд).
import { NextRequest, NextResponse } from "next/server";

import { disqualifyRequest } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  try {
    const body = (await request.json()) as { reason?: string; comment?: string | null };
    return NextResponse.json(
      await disqualifyRequest(
        id,
        { reason: body.reason ?? "", comment: body.comment ?? null },
        { id: user.id, fullName: user.fullName },
      ),
    );
  } catch (err) {
    return cashErrorResponse(err);
  }
}
