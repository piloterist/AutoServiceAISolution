// «Исправлено»: отметить ошибку разобранной (кто и когда - в журнале ошибки).
import { NextRequest, NextResponse } from "next/server";

import { resolveBayIssue } from "@/lib/backend-api";
import { getCurrentUser } from "@/lib/session";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  const body = (await request.json().catch(() => ({}))) as { note?: string | null };
  try {
    return NextResponse.json(await resolveBayIssue(id, body.note ?? null, { id: user.id, fullName: user.fullName }));
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
