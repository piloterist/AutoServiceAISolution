// Доска задач CRM: список карточек (с автопереходами по планировщику/заявкам/заказ-нарядам)
// и «На контроль» у звонка телефонии (цех обязателен).
import { NextRequest, NextResponse } from "next/server";

import { createCrmTask, getCrmTasks } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  const params = request.nextUrl.searchParams;
  try {
    return NextResponse.json(await getCrmTasks(params.get("workshop_id"), params.get("archived") === "1", params.get("employee_id")));
  } catch (err) {
    return cashErrorResponse(err);
  }
}

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  try {
    const body = (await request.json()) as { call_id?: string; workshop_id?: string; employee_id?: string | null };
    if (!body.call_id) return NextResponse.json({ error: "Не указан звонок" }, { status: 422 });
    if (!body.workshop_id) return NextResponse.json({ error: "Выберите цех" }, { status: 422 });
    return NextResponse.json(
      await createCrmTask(body.call_id, body.workshop_id, body.employee_id || null, { id: user.id, fullName: user.fullName }),
    );
  } catch (err) {
    return cashErrorResponse(err);
  }
}
