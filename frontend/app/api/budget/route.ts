// Proxies the Бюджет page - see components/budget/BudgetView.tsx and
// backend services/budget_service.py.
import { NextRequest, NextResponse } from "next/server";

import { type BudgetField, getBudgetYear, updateBudgetValue } from "@/lib/backend-api";

export async function GET(request: NextRequest) {
  const yearParam = request.nextUrl.searchParams.get("year");
  const year = yearParam ? Number(yearParam) : new Date().getFullYear();

  try {
    return NextResponse.json(await getBudgetYear(year));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function PUT(request: NextRequest) {
  const body = (await request.json()) as {
    workshop_id: string;
    year: number;
    month: number;
    field: BudgetField;
    value: number;
  };

  try {
    await updateBudgetValue({
      workshopId: body.workshop_id,
      year: body.year,
      month: body.month,
      field: body.field,
      value: body.value,
    });
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("422") ? 422 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}
