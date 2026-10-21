// Streams one call's recording live from Zeon (see backend
// services/call_recording_service.fetch_recording) through to the browser -
// same non-admin access as the rest of app/api/telephony/*, gated only by
// middleware.ts's general login+tab check.
import { NextResponse } from "next/server";

import { fetchCallRecording } from "@/lib/backend-api";

export async function GET(_request: Request, { params }: { params: Promise<{ callId: string }> }) {
  const { callId } = await params;
  const recording = await fetchCallRecording(callId);
  if (!recording) {
    return NextResponse.json({ error: "Recording not found" }, { status: 404 });
  }
  return new NextResponse(recording.body, {
    headers: { "Content-Type": recording.contentType, "Cache-Control": "private, max-age=3600" },
  });
}
