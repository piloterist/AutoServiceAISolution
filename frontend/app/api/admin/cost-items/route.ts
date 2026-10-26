// Настройки -> Финансы: the cost-item directory. Admin-only through
// middleware.ts (/api/admin/*), like every other Settings table.
import { NextRequest, NextResponse } from "next/server";

import { type CostItemWrite, createCostItem, getCostItems } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";

export async function GET() {
  try {
    return NextResponse.json(await getCostItems());
  } catch (err) {
    return cashErrorResponse(err);
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as CostItemWrite;
    return NextResponse.json(await createCostItem(body), { status: 201 });
  } catch (err) {
    return cashErrorResponse(err);
  }
}
