import { NextRequest, NextResponse } from "next/server";

import { absoluteUrl, SESSION_COOKIE_NAME } from "@/lib/auth";

export async function GET(request: NextRequest) {
  const response = NextResponse.redirect(absoluteUrl("/login", request));
  response.cookies.delete(SESSION_COOKIE_NAME);
  return response;
}
