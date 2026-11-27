// PUT/DELETE half of the camera directory proxy - see app/api/cameras/route.ts.
import { NextRequest, NextResponse } from "next/server";

import { deleteCamera, updateCamera, type CameraWrite } from "@/lib/backend-api";

export async function PUT(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = (await request.json()) as CameraWrite;

  try {
    return NextResponse.json(await updateCamera(id, body));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("409")
      ? 409
      : message.includes("422")
        ? 422
        : message.includes("404")
          ? 404
          : 502;
    const text =
      status === 409
        ? "Камера с таким кодом или MAC уже есть"
        : status === 422
          ? "Проверьте MAC-адрес: 12 цифр и букв A-F, например 9C-A2-F4-DA-22-EA"
          : message;
    return NextResponse.json({ error: text }, { status });
  }
}

export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  try {
    await deleteCamera(id);
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
