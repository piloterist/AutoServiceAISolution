// Касса: the entry dialog's work-order drop-down (the desk's last 100 days).
import { NextRequest, NextResponse } from "next/server";

import { searchCashWorkOrders } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });

  const workshopId = request.nextUrl.searchParams.get("workshop_id");
  if (!workshopId) return NextResponse.json({ error: "workshop_id is required" }, { status: 400 });

  try {
    return NextResponse.json(
      await searchCashWorkOrders(
        workshopId,
        request.nextUrl.searchParams.get("q") ?? "",
        { id: user.id, fullName: user.fullName },
      ),
    );
  } catch (err) {
    return cashErrorResponse(err);
  }
}
