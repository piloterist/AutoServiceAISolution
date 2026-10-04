// "Пересчитать цеха" button - see app/api/telephony/workshop-phones/route.ts
// for the directory this recomputes against.
import { NextResponse } from "next/server";

import { recomputeCallWorkshops } from "@/lib/backend-api";

export async function POST() {
  try {
    return NextResponse.json(await recomputeCallWorkshops());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
