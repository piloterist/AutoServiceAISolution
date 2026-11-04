// Статус запроса кадра (страница опрашивает, пока узел не ответит).
import { NextResponse } from "next/server";

import { getBaySnapshotRequest } from "@/lib/backend-api";

export async function GET(_request: Request, { params }: { params: Promise<{ requestId: string }> }) {
  const { requestId } = await params;
  try {
    return NextResponse.json(await getBaySnapshotRequest(requestId));
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 502 });
  }
}
