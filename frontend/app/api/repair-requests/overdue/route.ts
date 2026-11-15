// Контроль заявок: просроченные заявки - для колокольчика/всплывающего окна планировщика
// (цех пользователя) и для листа «Ошибки» (все цеха, только если вкладка «Ошибки» доступна).
import { NextRequest, NextResponse } from "next/server";

import { getOverdueRequests } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });

  const wantsAll = request.nextUrl.searchParams.get("scope") === "all";
  const mayReadAll = (user.allowedTabs ?? []).includes("/errors");
  const workshopId = request.nextUrl.searchParams.get("workshop_id") || undefined;
  try {
    return NextResponse.json(
      await getOverdueRequests(
        wantsAll && mayReadAll ? "all" : "mine",
        { id: user.id, fullName: user.fullName },
        workshopId,
      ),
    );
  } catch (err) {
    return cashErrorResponse(err);
  }
}
