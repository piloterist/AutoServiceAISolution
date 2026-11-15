// Доска задач CRM: окно лида (карточка, ссылки на заявку / заказ-наряд, комментарии).
import { NextRequest, NextResponse } from "next/server";

import { getCrmTaskDetail } from "@/lib/backend-api";
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
