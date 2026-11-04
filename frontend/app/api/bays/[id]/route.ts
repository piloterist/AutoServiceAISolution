// Переименовать/включить бокс (PATCH) и удалить (DELETE) - только Админ, см. middleware.ts.
import { NextRequest, NextResponse } from "next/server";

import { deleteBay, updateBay } from "@/lib/backend-api";

type Ctx = { params: Promise<{ id: string }> };

export async function PATCH(request: NextRequest, { params }: Ctx) {
  const { id } = await params;
  try {
    return NextResponse.json(await updateBay(id, await request.json()));
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}

export async function DELETE(_request: NextRequest, { params }: Ctx) {
  const { id } = await params;
  try {
    await deleteBay(id);
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
