// Доска задач CRM: комментарий к карточке (на любом этапе).
import { NextRequest, NextResponse } from "next/server";

import { addCrmTaskComment } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  try {
    const body = (await request.json()) as { text?: string; next_action_date?: string | null };
    if (!body.text?.trim()) {
      const error = body.next_action_date ? "Укажите комментарий к запланированному действию" : "Напишите комментарий";
      return NextResponse.json({ error }, { status: 422 });
    }
    return NextResponse.json(await addCrmTaskComment(id, body.text, body.next_action_date || null, { id: user.id, fullName: user.fullName }));
  } catch (err) {
    return cashErrorResponse(err);
  }
}
