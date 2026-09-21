// PUT/DELETE half of the generic Settings admin proxy - see
// app/api/admin/[resource]/route.ts (GET/POST) for the rest of the
// rationale.
import { NextRequest, NextResponse } from "next/server";

import {
  deleteOrgDepartment,
  deleteOrgUser,
  deleteSlesarkaStatus,
  deleteWorkshop,
  updateOrgDepartment,
  updateOrgUser,
  updateSlesarkaStatus,
  updateWorkshop,
  type OrgUserUpdate,
  type WorkshopWrite,
} from "@/lib/backend-api";

type Resource = "departments" | "workshops" | "users" | "slesarka-statuses";

function isResource(value: string): value is Resource {
  return value === "departments" || value === "workshops" || value === "users" || value === "slesarka-statuses";
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
    }
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
