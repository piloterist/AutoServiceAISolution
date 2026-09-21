import "server-only";

import { cookies } from "next/headers";

import { readSessionToken, SESSION_COOKIE_NAME, type SessionUser } from "@/lib/auth";

/** Resolves the current request's logged-in user from the signed cookie -
 * factored out of app/layout.tsx so route handlers (Planner proxy routes,
 * which need the actor's id/name for audit logging) can reuse it. Only
 * usable where next/headers' `cookies()` works (Server Components, Route
 * Handlers) - never in Edge middleware, which reads the cookie itself
 * (see middleware.ts). */
export async function getCurrentUser(): Promise<SessionUser | null> {
  const token = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  return readSessionToken(token);
}
