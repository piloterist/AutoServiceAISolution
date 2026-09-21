// Слесарный records for one workshop - list (by date range) and create.
// See app/api/admin/[resource]/route.ts for the general bridge-route
// rationale; POST additionally attaches the caller's own session identity
// as the audit-log actor (see lib/backend-api.ts's actorHeaders).
import { NextRequest, NextResponse } from "next/server";

import { createWorkshopJob, getWorkshopJobs, type WorkshopJobWrite } from "@/lib/backend-api";
import { getCurrentUser } from "@/lib/session";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ workshopId: string }> },
) {
  const { workshopId } = await params;
  const dateFrom = request.nextUrl.searchParams.get("date_from") ?? "";
  const dateTo = request.nextUrl.searchParams.get("date_to") ?? "";

  try {
    return NextResponse.json(await getWorkshopJobs(workshopId, dateFrom, dateTo));
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

  const payload = (await request.json()) as WorkshopJobWrite;
  try {
    const job = await createWorkshopJob(workshopId, payload, { id: user.id, fullName: user.fullName });
    return NextResponse.json(job, { status: 201 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("422") ? 422 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}
