// Касса: the cash book of one cash desk for a day/period. The backend decides
// from the caller's id (X-Actor-User-Id) which desks they may read - a desk
// they may not see answers 403.
import { NextRequest, NextResponse } from "next/server";

import { getCashBook } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });

  const params = request.nextUrl.searchParams;
  const workshopId = params.get("workshop_id");
  const dateFrom = params.get("date_from");
  if (!workshopId || !dateFrom) {
    return NextResponse.json({ error: "workshop_id and date_from are required" }, { status: 400 });
  }

  try {
    return NextResponse.json(
      await getCashBook(
        { workshopId, dateFrom, dateTo: params.get("date_to") ?? dateFrom },
        { id: user.id, fullName: user.fullName },
      ),
    );
  } catch (err) {
    return cashErrorResponse(err);
  }
}
