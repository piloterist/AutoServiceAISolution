// Касса: change or delete one entry. PUT with an amount of 0 deletes it (the
// backend answers `deleted: true`); every change is written to the audit log.
import { NextRequest, NextResponse } from "next/server";

import { deleteCashEntry, updateCashEntry, type CashEntryWrite } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function PUT(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });

  try {
    return NextResponse.json(
      await updateCashEntry(id, (await request.json()) as CashEntryWrite, {
        id: user.id,
        fullName: user.fullName,
      }),
    );
  } catch (err) {
    return cashErrorResponse(err);
  }
}

export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });

  try {
    await deleteCashEntry(id, { id: user.id, fullName: user.fullName });
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    return cashErrorResponse(err);
  }
}
