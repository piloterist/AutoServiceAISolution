// Сколько ошибок не исправлено - по этому числу вкладка «Ошибки» красная или серая (Nav.tsx):
// ошибки видеоконтроля плюс просроченные звонки по заявкам (они закрываются сами).
import { NextResponse } from "next/server";

import { getBayIssueSummary, getOverdueRequests } from "@/lib/backend-api";
import { getCurrentUser } from "@/lib/session";

export async function GET() {
  try {
    const user = await getCurrentUser();
    const actor = { id: user?.id ?? "", fullName: user?.fullName ?? "" };
    const [bays, requests] = await Promise.all([getBayIssueSummary(), getOverdueRequests("all", actor)]);
    return NextResponse.json({ open_count: bays.open_count + requests.items.length });
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
