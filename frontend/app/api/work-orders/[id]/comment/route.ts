// Proxies the work order comment save - WorkOrderComment is a client
// component and can't import lib/backend-api.ts directly (it's
// server-only), same bridge pattern as app/api/work-orders/route.ts.
import { NextRequest, NextResponse } from "next/server";

import { updateWorkOrderComment } from "@/lib/backend-api";

export async function PATCH(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  try {
    const body = await request.json();
    const data = await updateWorkOrderComment(id, body.comment ?? null);
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
