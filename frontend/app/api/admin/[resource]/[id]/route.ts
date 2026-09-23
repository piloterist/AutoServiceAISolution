// PUT/DELETE half of the generic Settings admin proxy - see
// app/api/admin/[resource]/route.ts (GET/POST) for the rest of the
// rationale.
import { NextRequest, NextResponse } from "next/server";

import {
  deleteEmployee,
  deleteOrgDepartment,
  deleteOrgUser,
  deleteRoleTabVisibility,
  deleteSlesarkaStatus,
  deleteWorkshop,
  updateEmployee,
  updateOrgDepartment,
  updateOrgUser,
  updateRoleTabVisibility,
  updateSlesarkaStatus,
  updateWorkshop,
  type EmployeeWrite,
  type OrgUserUpdate,
  type RoleTabVisibilityWrite,
  type WorkshopWrite,
} from "@/lib/backend-api";

type Resource =
  | "departments"
  | "workshops"
  | "users"
  | "slesarka-statuses"
  | "employees"
  | "role-tab-visibility";

function isResource(value: string): value is Resource {
  return (
    value === "departments" ||
    value === "workshops" ||
    value === "users" ||
    value === "slesarka-statuses" ||
    value === "employees" ||
    value === "role-tab-visibility"
  );
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ resource: string; id: string }> },
) {
  const { resource, id } = await params;
  if (!isResource(resource)) return NextResponse.json({ error: "Unknown resource" }, { status: 404 });

  const body = await request.json();

  try {
    switch (resource) {
      case "departments":
        return NextResponse.json(await updateOrgDepartment(id, body.name));
      case "workshops":
        return NextResponse.json(await updateWorkshop(id, body as WorkshopWrite));
      case "users":
        return NextResponse.json(await updateOrgUser(id, body as OrgUserUpdate));
      case "slesarka-statuses":
        return NextResponse.json(await updateSlesarkaStatus(id, body.name, body.color));
      case "employees":
        return NextResponse.json(await updateEmployee(id, body as EmployeeWrite));
      case "role-tab-visibility":
        return NextResponse.json(await updateRoleTabVisibility(id, body as RoleTabVisibilityWrite));
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("409")
      ? 409
      : message.includes("422")
        ? 422
        : message.includes("404")
          ? 404
          : 502;
    return NextResponse.json({ error: message }, { status });
  }
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ resource: string; id: string }> },
) {
  const { resource, id } = await params;
  if (!isResource(resource)) return NextResponse.json({ error: "Unknown resource" }, { status: 404 });

  try {
    switch (resource) {
      case "departments":
        await deleteOrgDepartment(id);
        break;
      case "workshops":
        await deleteWorkshop(id);
        break;
      case "users":
        await deleteOrgUser(id);
        break;
      case "slesarka-statuses":
        await deleteSlesarkaStatus(id);
        break;
      case "employees":
        await deleteEmployee(id);
        break;
      case "role-tab-visibility":
        await deleteRoleTabVisibility(id);
        break;
    }
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
