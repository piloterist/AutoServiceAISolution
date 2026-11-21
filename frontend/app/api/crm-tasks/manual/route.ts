// Доска задач CRM: «Создать» - карточка, заполненная руками (телефон и цех обязательны).
import { NextRequest, NextResponse } from "next/server";

import { createManualCrmTask, type ManualCrmTaskInput } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  try {
    const body = (await request.json()) as Partial<ManualCrmTaskInput>;
    if (!body.phone?.trim()) return NextResponse.json({ error: "Укажите телефон" }, { status: 422 });
    if (!body.workshop_id) return NextResponse.json({ error: "Выберите цех" }, { status: 422 });
    return NextResponse.json(
      await createManualCrmTask(
        {
          phone: body.phone,
          workshop_id: body.workshop_id,
          employee_id: body.employee_id || null,
          client_name: body.client_name?.trim() || null,
          comment: body.comment?.trim() || null,
          action_date: body.action_date || null,
          action_comment: body.action_comment?.trim() || null,
        },
        { id: user.id, fullName: user.fullName },
      ),
    );
  } catch (err) {
    return cashErrorResponse(err);
  }
}
