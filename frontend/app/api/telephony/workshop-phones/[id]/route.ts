// PUT/DELETE half of the "Цех — Телефон — Добавочный" proxy - see
// app/api/telephony/workshop-phones/route.ts (GET/POST).
import { NextRequest, NextResponse } from "next/server";

import {
  deleteWorkshopPhoneMapping,
  updateWorkshopPhoneMapping,
  type WorkshopPhoneMappingWrite,
} from "@/lib/backend-api";

export async function PUT(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = (await request.json()) as WorkshopPhoneMappingWrite;

  try {
    return NextResponse.json(await updateWorkshopPhoneMapping(id, body));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("422") ? 422 : message.includes("404") ? 404 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}

export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  try {
    await deleteWorkshopPhoneMapping(id);
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
