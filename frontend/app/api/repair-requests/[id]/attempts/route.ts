// Ручная отметка попытки связаться с клиентом (комментарий обязателен).
import { NextRequest, NextResponse } from "next/server";

import { addRequestAttempt } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  try {
    const body = (await request.json()) as { comment?: string; attempted_at?: string | null };
    return NextResponse.json(
      await addRequestAttempt(
        id,
        { comment: body.comment ?? "", attempted_at: body.attempted_at ?? null },
        { id: user.id, fullName: user.fullName },
      ),
    );
  } catch (err) {
    return cashErrorResponse(err);
  }
}
