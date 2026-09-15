import { NextRequest, NextResponse } from "next/server";

import { absoluteUrl, isValidSessionToken, SESSION_COOKIE_NAME } from "@/lib/auth";

// Gates every page behind the login cookie - the site is otherwise public
// (no per-user auth system yet, see ARCHITECTURE.md), and this exists
// purely to keep it from being wide open to anyone who has the URL.
export async function middleware(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (await isValidSessionToken(token)) {
    return NextResponse.next();
  }

  const loginUrl = absoluteUrl("/login", request);
  loginUrl.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!api/auth|login|_next/static|_next/image|favicon.ico|pan-motors-logo.png).*)"],
};
