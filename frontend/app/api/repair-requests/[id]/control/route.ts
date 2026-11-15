// Контроль заявки: статус, попытки, сроки и что можно сделать (карточка заявки).
import { NextRequest, NextResponse } from "next/server";

import { getRequestControl } from "@/lib/backend-api";
import { cashErrorResponse } from "@/lib/cash-errors";
import { getCurrentUser } from "@/lib/session";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  try {
    return NextResponse.json(await getRequestControl(id, { id: user.id, fullName: user.fullName }));
  } catch (err) {
    return cashErrorResponse(err);
  }
}
