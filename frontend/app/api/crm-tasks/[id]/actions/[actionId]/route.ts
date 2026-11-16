// Доска задач CRM: изменить или удалить запланированное действие карточки.
import { NextRequest, NextResponse } from "next/server";

import { deleteCrmTaskAction, updateCrmTaskAction } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

type Ctx = { params: Promise<{ id: string; actionId: string }> };

export async function PATCH(request: NextRequest, { params }: Ctx) {
  const { id, actionId } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  try {
    const body = (await request.json()) as { planned_date?: string; comment?: string };
    if (!body.planned_date) return NextResponse.json({ error: "Укажите дату" }, { status: 422 });
    if (!body.comment?.trim()) {
      return NextResponse.json({ error: "Укажите комментарий к запланированному действию" }, { status: 422 });
    }
    return NextResponse.json(await updateCrmTaskAction(id, actionId, { planned_date: body.planned_date, comment: body.comment }));
  } catch (err) {
    return cashErrorResponse(err);
  }
}

export async function DELETE(_request: NextRequest, { params }: Ctx) {
  const { id, actionId } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  try {
    await deleteCrmTaskAction(id, actionId);
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    return cashErrorResponse(err);
  }
}
