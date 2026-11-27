// Proxies the camera directory list/create - Settings -> Камеры. Admin-only (middleware.ts).
import { NextRequest, NextResponse } from "next/server";

import { createCamera, getCameras, type CameraWrite } from "@/lib/backend-api";

export async function GET() {
  try {
    return NextResponse.json(await getCameras());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function POST(request: NextRequest) {
  const body = (await request.json()) as CameraWrite;

  try {
    return NextResponse.json(await createCamera(body), { status: 201 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("409") ? 409 : message.includes("422") ? 422 : 502;
    const text =
      status === 409
        ? "Камера с таким кодом или MAC уже есть"
        : status === 422
          ? "Проверьте MAC-адрес: 12 цифр и букв A-F, например 9C-A2-F4-DA-22-EA"
          : message;
    return NextResponse.json({ error: text }, { status });
  }
}
