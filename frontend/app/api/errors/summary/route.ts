// Сколько ошибок не исправлено - по этому числу вкладка «Ошибки» красная или серая (Nav.tsx).
import { NextResponse } from "next/server";

import { getBayIssueSummary } from "@/lib/backend-api";

export async function GET() {
  try {
    return NextResponse.json(await getBayIssueSummary());
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
