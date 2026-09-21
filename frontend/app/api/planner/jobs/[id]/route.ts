// Update/delete one Слесарный record - see .../workshops/[workshopId]/jobs/route.ts
// for list/create.
import { NextRequest, NextResponse } from "next/server";

import { deleteWorkshopJob, updateWorkshopJob, type WorkshopJobWrite } from "@/lib/backend-api";
import { getCurrentUser } from "@/lib/session";

export async function PUT(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });

  const payload = (await request.json()) as WorkshopJobWrite;
  try {
    const job = await updateWorkshopJob(id, payload, { id: user.id, fullName: user.fullName });
    return NextResponse.json(job);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("422") ? 422 : message.includes("404") ? 404 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}

export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });

  try {
    await deleteWorkshopJob(id, { id: user.id, fullName: user.fullName });
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: message.includes("404") ? 404 : 502 });
  }
}
