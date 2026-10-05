// "Выполнить сейчас" button next to the planner_auto_match_* settings - see
// app/api/telephony/workshop-phones/recompute/route.ts for the same
// on-demand-run-of-a-background-job pattern.
import { NextResponse } from "next/server";

import { runPlannerAutoMatch } from "@/lib/backend-api";

export async function POST() {
  try {
    return NextResponse.json(await runPlannerAutoMatch());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
