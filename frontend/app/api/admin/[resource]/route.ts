// Generic proxy for the Settings admin tables (Пользователи/Подразделения/
// Цеха/Статусы слесарки/аудит-лог) - same bridge role as app/api/settings/
// route.ts, just parameterized over `resource` instead of one file per
// table, since all five follow the same list/create shape. Role gating
// (Admin only) happens in middleware.ts, same as page access to /settings -
// this route trusts that gate exactly like it trusts BACKEND_API_TOKEN
// being the only thing standing between it and the backend.
import { NextRequest, NextResponse } from "next/server";

import {
  createEmployee,
  createOrgDepartment,
  createOrgUser,
  createRoleTabVisibility,
  createSlesarkaStatus,
  createWorkshop,
  getAuditLog,
  getEmployees,
  getOrgDepartments,
  getOrgUsers,
  getRoleTabVisibility,
  getSlesarkaStatuses,
  getWorkshops,
  type EmployeeWrite,
  type OrgUserCreate,
  type RoleTabVisibilityWrite,
  type WorkshopWrite,
} from "@/lib/backend-api";

type Resource =
  | "departments"
  | "workshops"
  | "users"
  | "slesarka-statuses"
  | "audit-log"
  | "employees"
  | "role-tab-visibility";

function isResource(value: string): value is Resource {
  return (
    value === "departments" ||
    value === "workshops" ||
    value === "users" ||
    value === "slesarka-statuses" ||
    value === "audit-log" ||
    value === "employees" ||
    value === "role-tab-visibility"
  );
}

export async function GET(_request: NextRequest, { params }: { params: Promise<{ resource: string }> }) {
  const { resource } = await params;
  if (!isResource(resource)) return NextResponse.json({ error: "Unknown resource" }, { status: 404 });

  try {
    switch (resource) {
      case "departments":
        return NextResponse.json(await getOrgDepartments());
      case "workshops":
        return NextResponse.json(await getWorkshops());
      case "users":
        return NextResponse.json(await getOrgUsers());
      case "slesarka-statuses":
        return NextResponse.json(await getSlesarkaStatuses());
      case "audit-log":
        return NextResponse.json(await getAuditLog());
      case "employees":
        return NextResponse.json(await getEmployees());
      case "role-tab-visibility":
        return NextResponse.json(await getRoleTabVisibility());
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ resource: string }> }) {
  const { resource } = await params;
  if (!isResource(resource) || resource === "audit-log") {
    return NextResponse.json({ error: "Unknown resource" }, { status: 404 });
  }

  const body = await request.json();

  try {
    switch (resource) {
      case "departments":
        return NextResponse.json(await createOrgDepartment(body.name), { status: 201 });
      case "workshops":
        return NextResponse.json(await createWorkshop(body as WorkshopWrite), { status: 201 });
      case "users":
        return NextResponse.json(await createOrgUser(body as OrgUserCreate), { status: 201 });
      case "slesarka-statuses":
        return NextResponse.json(await createSlesarkaStatus(body.name, body.color), { status: 201 });
      case "employees":
        return NextResponse.json(await createEmployee(body as EmployeeWrite), { status: 201 });
      case "role-tab-visibility":
        return NextResponse.json(await createRoleTabVisibility(body as RoleTabVisibilityWrite), {
          status: 201,
        });
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("409") ? 409 : message.includes("422") ? 422 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}
