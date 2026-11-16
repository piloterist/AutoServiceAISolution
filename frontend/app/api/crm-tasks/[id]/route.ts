// Доска задач CRM: окно лида (карточка, ссылки на заявку / заказ-наряд, комментарии).
import { NextRequest, NextResponse } from "next/server";

import { assignCrmTask, getCrmTaskDetail } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  try {
    return NextResponse.json(await getCrmTaskDetail(id));
  } catch (err) {
    return cashErrorResponse(err);
  }
}

// Сменить цех и сотрудника карточки.
export async function PATCH(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  try {
    const body = (await request.json()) as { workshop_id?: string | null; employee_id?: string | null };
    if (!body.workshop_id) return NextResponse.json({ error: "Выберите цех" }, { status: 422 });
    return NextResponse.json(
      await assignCrmTask(
        id,
        { workshop_id: body.workshop_id, employee_id: body.employee_id || null },
        { id: user.id, fullName: user.fullName },
      ),
    );
  } catch (err) {
    return cashErrorResponse(err);
  }
}
