// Настройки -> Финансы: saves the hand-made order of the cost items (drag and
// drop). Admin-only through middleware.ts (/api/admin/*).
import { NextRequest, NextResponse } from "next/server";

import { reorderCostItems } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";

export async function PUT(request: NextRequest) {
  try {
    const body = (await request.json()) as { ids: string[] };
    return NextResponse.json(await reorderCostItems(body.ids));
  } catch (err) {
    return cashErrorResponse(err);
  }
}
