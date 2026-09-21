// Кузовной records for one workshop - list and create. See
// .../jobs/route.ts (Слесарный) for the same shape, and
// app/api/admin/[resource]/route.ts for the general bridge-route rationale.
import { NextRequest, NextResponse } from "next/server";

import { createBodyCar, getBodyCars, type BodyCarWrite } from "@/lib/backend-api";
import { getCurrentUser } from "@/lib/session";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ workshopId: string }> },
) {
  const { workshopId } = await params;
  try {
    return NextResponse.json(await getBodyCars(workshopId));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ workshopId: string }> },
) {
  const { workshopId } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });

  const payload = (await request.json()) as BodyCarWrite;
  try {
    const car = await createBodyCar(workshopId, payload, { id: user.id, fullName: user.fullName });
    return NextResponse.json(car, { status: 201 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("422") ? 422 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}
