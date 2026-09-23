import { NextRequest, NextResponse } from "next/server";

import {
  absoluteUrl,
  createSessionToken,
  safeNextPath,
  SESSION_COOKIE_NAME,
  SESSION_MAX_AGE_SECONDS,
} from "@/lib/auth";
import { loginUser } from "@/lib/backend-api";

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const username = String(formData.get("username") ?? "");
  const password = String(formData.get("password") ?? "");
  const next = safeNextPath(String(formData.get("next") ?? ""));

  let user;
  try {
    user = await loginUser(username, password);
  } catch {
    const loginUrl = absoluteUrl("/login", request);
    loginUrl.searchParams.set("error", "1");
    loginUrl.searchParams.set("next", next);
    return NextResponse.redirect(loginUrl, { status: 303 });
  }

  const token = await createSessionToken({
    id: user.id,
    fullName: user.full_name,
    login: user.login,
    role: user.role,
    departmentId: user.department_id,
    departmentName: user.department_name,
    workshopId: user.workshop_id,
    allowedTabs: user.allowed_tabs,
  });
  const response = NextResponse.redirect(absoluteUrl(next, request), { status: 303 });
  response.cookies.set(SESSION_COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  return response;
}
