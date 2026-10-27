// Касса -> "В Excel": the cash book of one desk over a period as an .xlsx download.
// The backend decides from the caller's id which desks they may read (403 otherwise).
import { NextRequest, NextResponse } from "next/server";

import { getCashExcel } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });

  const params = request.nextUrl.searchParams;
  const workshopId = params.get("workshop_id");
  const dateFrom = params.get("date_from");
  const dateTo = params.get("date_to");
  if (!workshopId || !dateFrom || !dateTo) {
    return NextResponse.json(
      { error: "workshop_id, date_from and date_to are required" },
      { status: 400 },
    );
  }

  try {
    const file = await getCashExcel(
      { workshopId, dateFrom, dateTo },
      { id: user.id, fullName: user.fullName },
    );
    return new NextResponse(file.body, {
      headers: {
        "Content-Type": file.contentType,
        ...(file.contentDisposition ? { "Content-Disposition": file.contentDisposition } : {}),
        "Cache-Control": "no-store",
      },
    });
  } catch (err) {
    return cashErrorResponse(err);
  }
}
