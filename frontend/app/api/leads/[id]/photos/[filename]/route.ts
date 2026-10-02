// Streams a lead's photo from our own Yandex.Disk archive (see backend
// services/lead_photos_service.py) through to the browser - same
// non-admin access as ../../route.ts and ../open/route.ts, gated only by
// middleware.ts's general login+tab check, not the Admin-only leads gate.
import { NextResponse } from "next/server";

import { fetchLeadPhoto } from "@/lib/backend-api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string; filename: string }> },
) {
  const { id, filename } = await params;
  const photo = await fetchLeadPhoto(id, filename);
  if (!photo) {
    return NextResponse.json({ error: "Photo not found" }, { status: 404 });
  }
  return new NextResponse(photo.body, {
    headers: { "Content-Type": photo.contentType, "Cache-Control": "private, max-age=86400" },
  });
}
