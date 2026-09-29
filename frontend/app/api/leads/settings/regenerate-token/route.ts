// Rotates the site's intake token - shown exactly once in the response,
// same handling as any other write-only secret in this app.
import { NextResponse } from "next/server";

import { regenerateLeadsIntakeToken } from "@/lib/backend-api";

export async function POST() {
  try {
    return NextResponse.json(await regenerateLeadsIntakeToken());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
