import { NextRequest, NextResponse } from "next/server";

import {
  absoluteUrl,
  readSessionToken,
  ROLE_ADMIN,
  ROLE_SERVICE_ADVISOR,
  SESSION_COOKIE_NAME,
} from "@/lib/auth";

// Gates every page behind the login cookie - without this the site would
// otherwise be reachable by anyone with the URL. /settings and its API
// proxy (/api/admin/*) additionally require the Admin role - the only
// place in this app role matters yet (see product brief: "Раздел
// настроек... доступен только для пользователя с ролью Админ"). Мастер
// приёмщик is the mirror-image restriction: locked to ONLY /planner (+ the
// /api/planner/* proxy calls the Planner page itself needs) - a top-nav-
// tabs-level restriction only, nothing inside the Planner (choosing a ЗН,
// etc.) is further gated by role.
export async function middleware(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  const user = await readSessionToken(token);

  if (!user) {
    const loginUrl = absoluteUrl("/login", request);
    loginUrl.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
    return NextResponse.redirect(loginUrl);
  }

  const { pathname } = request.nextUrl;

  if (user.role === ROLE_SERVICE_ADVISOR) {
    const isPlannerArea =
      pathname === "/planner" || pathname.startsWith("/planner/") || pathname.startsWith("/api/planner");
    if (!isPlannerArea) {
      if (pathname.startsWith("/api/")) {
        return NextResponse.json({ error: "Доступна только страница Планировщик" }, { status: 403 });
      }
      return NextResponse.redirect(absoluteUrl("/planner", request));
    }
  }

  const isAdminApi = pathname.startsWith("/api/admin");
  const isAdminArea = pathname.startsWith("/settings") || isAdminApi;

  if (isAdminArea && user.role !== ROLE_ADMIN) {
    if (isAdminApi) return NextResponse.json({ error: "Admin role required" }, { status: 403 });
    return NextResponse.redirect(absoluteUrl("/dashboard", request));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api/auth|login|_next/static|_next/image|favicon.ico|pan-motors-logo.png).*)"],
};
