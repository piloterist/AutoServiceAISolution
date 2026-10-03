import { NextRequest, NextResponse } from "next/server";

import { absoluteUrl, readSessionToken, ROLE_ADMIN, SESSION_COOKIE_NAME } from "@/lib/auth";
import { NAV_TAB_KEYS, type NavTabKey } from "@/lib/nav-tabs";

// Which configurable NAV_TABS entry (if any) a request path belongs to -
// the page itself, or (for /planner only) its dedicated API proxy
// namespace. Every other tab's data comes through /api/work-orders or
// /api/settings, shared across multiple tabs, so it can't be gated per-tab
// without breaking tabs that ARE allowed - see RoleTabVisibilityCard.tsx's
// module comment for the same scoping note.
function tabForPath(pathname: string): NavTabKey | null {
  for (const key of NAV_TAB_KEYS) {
    if (pathname === key || pathname.startsWith(`${key}/`)) return key;
  }
  if (pathname === "/api/planner" || pathname.startsWith("/api/planner/")) return "/planner";
  return null;
}

// Gates every page behind the login cookie - without this the site would
// otherwise be reachable by anyone with the URL. /settings and its API
// proxy (/api/admin/*) additionally require the Admin role - not part of
// the configurable NAV_TABS below, deliberately hardcoded so a role's own
// visible-tabs list can never be edited into a state that locks every
// admin out of the page that edits it (see Settings → Пользователи →
// "Права доступа"). Every other tab's visibility comes from the session
// cookie's allowedTabs (baked in at login from RoleTabVisibility - see
// lib/auth.ts, app/api/auth/login/route.ts) - a top-nav-tabs-level
// restriction only, nothing inside an allowed page (e.g. choosing a ЗН in
// the Planner) is further gated by role.
export async function middleware(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  const user = await readSessionToken(token);

  if (!user) {
    const loginUrl = absoluteUrl("/login", request);
    loginUrl.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
    return NextResponse.redirect(loginUrl);
  }

  // Daily auto-logout (Settings -> Общие -> "Автовыход в") - every role
  // except Admin gets bounced back to /login once Date.now() reaches the
  // boundary baked into their session at login (see lib/auth.ts's
  // nextDailyBoundary). Checked before anything else below, same as the
  // "no cookie at all" branch above - an expired-by-this-rule session is
  // otherwise indistinguishable from any other logged-out visitor.
  if (user.role !== ROLE_ADMIN && Date.now() >= user.logoutAt) {
    // An API route gets a clean 401, not an HTML redirect response - a
    // background poll (e.g. LeadsBadge's 60s interval) would otherwise
    // auto-follow the redirect and choke on the login page's HTML where it
    // expects JSON. Same branch shape as the allowedTabs check below.
    if (request.nextUrl.pathname.startsWith("/api/")) {
      const response = NextResponse.json({ error: "Сессия истекла" }, { status: 401 });
      response.cookies.delete(SESSION_COOKIE_NAME);
      return response;
    }
    const loginUrl = absoluteUrl("/login", request);
    loginUrl.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
    const response = NextResponse.redirect(loginUrl);
    response.cookies.delete(SESSION_COOKIE_NAME);
    return response;
  }

  const { pathname } = request.nextUrl;

  // Falls back to "no tabs allowed" (not "every tab allowed") for a cookie
  // signed before allowedTabs existed - safe by construction, since such a
  // cookie is stale and the user needs to log back in anyway to pick up a
  // fresh one (see lib/auth.ts's SessionUser.allowedTabs comment).
  const allowedTabs = user.allowedTabs ?? [];
  const tab = tabForPath(pathname);
  if (tab && !allowedTabs.includes(tab)) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "Доступ к этому разделу ограничен" }, { status: 403 });
    }
    return NextResponse.redirect(absoluteUrl(allowedTabs[0] ?? "/cockpit", request));
  }

  // /api/telephony/settings, /sources and the ping/import actions are only
  // ever called from the Settings -> "IP-телефония" tab (connection
  // credentials, phone-source directory) - same Admin-only gate as
  // /api/admin/*. /api/telephony/source-summary is deliberately excluded:
  // it feeds the /telephony stats page itself, which any role with that
  // tab allowed (via allowedTabs, checked above) should be able to read.
  const isTelephonyAdminApi =
    pathname.startsWith("/api/telephony/settings") ||
    pathname.startsWith("/api/telephony/sources") ||
    pathname.startsWith("/api/telephony/ping") ||
    pathname.startsWith("/api/telephony/import") ||
    pathname.startsWith("/api/telephony/recordings");
  // /api/leads/settings (incl. its regenerate-token action) is the
  // connection config for Заявки, same Admin-only gate as telephony's own
  // settings above. /api/leads and /api/leads/open (full history page +
  // Planner envelope badge) are deliberately excluded, same reasoning as
  // /api/telephony/source-summary and /api/telephony/missed-calls above.
  const isLeadsAdminApi = pathname.startsWith("/api/leads/settings");
  const isAdminApi = pathname.startsWith("/api/admin") || isTelephonyAdminApi || isLeadsAdminApi;
  const isAdminArea = pathname.startsWith("/settings") || isAdminApi;

  if (isAdminArea && user.role !== ROLE_ADMIN) {
    if (isAdminApi) return NextResponse.json({ error: "Admin role required" }, { status: 403 });
    return NextResponse.redirect(absoluteUrl("/cockpit", request));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api/auth|login|_next/static|_next/image|favicon.ico|pan-motors-logo.png).*)"],
};
