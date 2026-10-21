// Expanded lead detail card's call-history section (product ask,
// 2026-10-21) - same non-admin access as ../../route.ts and
// ../photos/[filename]/route.ts.
import { NextResponse } from "next/server";

import { getLeadCalls } from "@/lib/backend-api";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    return NextResponse.json(await getLeadCalls(id));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
