// Proxies the "Закрыть без оплат" checkbox save - Админ role only, gated
// by middleware.ts's isAdminApi (same convention as /api/admin/*,
// /api/telephony/settings, /api/leads/settings - no in-handler role check
// here either, see those routes). WorkOrderClosedWithoutPayment is a
// client component and can't import lib/backend-api.ts directly (it's
// server-only), same bridge pattern as .../comment/route.ts.
import { NextRequest, NextResponse } from "next/server";

import { updateWorkOrderClosedWithoutPayment } from "@/lib/backend-api";

export async function PATCH(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  try {
    const body = await request.json();
    const data = await updateWorkOrderClosedWithoutPayment(id, Boolean(body.closed_without_payment));
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
