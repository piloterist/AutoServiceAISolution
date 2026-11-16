// Доска задач CRM: перенос карточки в другой столбец (в «Отказ» - с обязательной причиной).
import { NextRequest, NextResponse } from "next/server";

import { moveCrmTask, type CrmTaskStatus } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  try {
    const body = (await request.json()) as {
      status?: CrmTaskStatus;
      reason?: string | null;
      body_car_id?: string | null;
      workshop_job_id?: string | null;
    };
    if (!body.status) return NextResponse.json({ error: "Не указан столбец" }, { status: 422 });
    return NextResponse.json(
      await moveCrmTask(
        id,
        {
          status: body.status,
          reason: body.reason ?? null,
          body_car_id: body.body_car_id ?? null,
          workshop_job_id: body.workshop_job_id ?? null,
        },
        { id: user.id, fullName: user.fullName },
      ),
    );
  } catch (err) {
    return cashErrorResponse(err);
  }
}
