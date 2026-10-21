// Proxies the Финансы -> Дебиторская задолженность tab - see
// components/budget/ReceivablesAgingView.tsx and backend
// services/receivables_service.py.
import { NextResponse } from "next/server";

import { getReceivablesAging } from "@/lib/backend-api";

export async function GET() {
  try {
    return NextResponse.json(await getReceivablesAging());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
