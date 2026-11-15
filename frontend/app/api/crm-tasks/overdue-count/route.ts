// Доска задач CRM: сколько карточек «На контроле» дошло до розового срока (для значка планировщика,
// по цеху, выбранному в планировщике).
import { NextRequest, NextResponse } from "next/server";

import { getCrmTaskOverdueCount } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  try {
    return NextResponse.json(await getCrmTaskOverdueCount(request.nextUrl.searchParams.get("workshop_id")));
  } catch (err) {
    return cashErrorResponse(err);
  }
}
