// PUT/DELETE half of the phone-source directory proxy - see
// app/api/telephony/sources/route.ts (GET/POST).
import { NextRequest, NextResponse } from "next/server";

import { deletePhoneSource, type PhoneSourceWrite, updatePhoneSource } from "@/lib/backend-api";

export async function PUT(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = (await request.json()) as PhoneSourceWrite;

  try {
    return NextResponse.json(await updatePhoneSource(id, body));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("409")
      ? 409
      : message.includes("422")
        ? 422
        : message.includes("404")
          ? 404
          : 502;
    return NextResponse.json({ error: message }, { status });
  }
}

export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  try {
    await deletePhoneSource(id);
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
