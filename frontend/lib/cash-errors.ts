import "server-only";

import { NextResponse } from "next/server";

/** Turns a failed backend call ("Backend request failed: 423 {"detail":...}")
 * into a JSON error response carrying the backend's own readable message
 * (e.g. "Дата 10.10.2026 в заблокированном периоде…") and a matching status,
 * so the cash dialog can show it as is. */
export function cashErrorResponse(err: unknown): NextResponse {
  const message = err instanceof Error ? err.message : "Unknown error";
  const match = /(\d{3}) ([\s\S]*)$/.exec(message);
  if (!match) return NextResponse.json({ error: message }, { status: 502 });

  const status = Number(match[1]);
  let detail = match[2];
  try {
    const parsed = JSON.parse(match[2]) as { detail?: unknown };
    if (typeof parsed.detail === "string") detail = parsed.detail;
    else if (Array.isArray(parsed.detail)) detail = "Проверьте заполнение полей";
  } catch {
    // not JSON - keep the raw text
  }
  return NextResponse.json({ error: detail }, { status: status >= 400 && status < 600 ? status : 502 });
}
