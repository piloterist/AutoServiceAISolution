// Финансы -> Расходы - see components/budget/ExpensesView.tsx and the
// backend services/finance_service.py. Gated to the Финансы tab in
// middleware.ts.
import { NextRequest, NextResponse } from "next/server";

import { getExpensesYear, setExpense } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";

export async function GET(request: NextRequest) {
  const yearParam = request.nextUrl.searchParams.get("year");
  const year = yearParam ? Number(yearParam) : new Date().getFullYear();
  try {
    return NextResponse.json(await getExpensesYear(year));
  } catch (err) {
    return cashErrorResponse(err);
  }
}

export async function PUT(request: NextRequest) {
  try {
    const body = (await request.json()) as {
      cost_item_id: string;
      workshop_id: string;
      year: number;
      month: number;
      amount: string;
    };
    await setExpense(body);
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    return cashErrorResponse(err);
  }
}
