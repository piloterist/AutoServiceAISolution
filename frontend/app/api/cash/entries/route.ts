// Касса: create an entry.
import { NextRequest, NextResponse } from "next/server";

import { createCashEntry, type CashEntryWrite } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });

  try {
    const entry = await createCashEntry((await request.json()) as CashEntryWrite, {
      id: user.id,
      fullName: user.fullName,
    });
    return NextResponse.json(entry, { status: 201 });
  } catch (err) {
    return cashErrorResponse(err);
  }
}
