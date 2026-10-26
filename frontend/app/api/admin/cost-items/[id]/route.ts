import { NextRequest, NextResponse } from "next/server";

import { type CostItemWrite, deleteCostItem, updateCostItem } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";

export async function PUT(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const body = (await request.json()) as CostItemWrite;
    return NextResponse.json(await updateCostItem(id, body));
  } catch (err) {
    return cashErrorResponse(err);
  }
}

export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    await deleteCostItem(id);
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    return cashErrorResponse(err);
  }
}
