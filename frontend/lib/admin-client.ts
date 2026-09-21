"use client";

// Client-side fetch wrappers for the Settings admin tables, talking to the
// generic proxy at app/api/admin/[resource]/(.../[id])/route.ts - the
// client-safe counterpart to the server-only functions in lib/backend-api.ts
// (whose types are reused here via `import type`, which TypeScript erases
// entirely, so none of that file's server-only code reaches the browser
// bundle).
import type {
  AuditLogEntry,
  OrgDepartment,
  OrgUser,
  OrgUserCreate,
  OrgUserUpdate,
  SlesarkaStatus,
  Workshop,
  WorkshopWrite,
} from "@/lib/backend-api";

async function proxyFetch<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(typeof body.error === "string" ? body.error : `Request failed: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const jsonHeaders = { "Content-Type": "application/json" };

export const departmentsApi = {
  list: () => proxyFetch<OrgDepartment[]>("/api/admin/departments"),
  create: (name: string) =>
    proxyFetch<OrgDepartment>("/api/admin/departments", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name }),
    }),
  update: (id: string, name: string) =>
    proxyFetch<OrgDepartment>(`/api/admin/departments/${id}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify({ name }),
    }),
  remove: (id: string) => proxyFetch<void>(`/api/admin/departments/${id}`, { method: "DELETE" }),
};

export const workshopsApi = {
  list: () => proxyFetch<Workshop[]>("/api/admin/workshops"),
  create: (payload: WorkshopWrite) =>
    proxyFetch<Workshop>("/api/admin/workshops", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: WorkshopWrite) =>
    proxyFetch<Workshop>(`/api/admin/workshops/${id}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  remove: (id: string) => proxyFetch<void>(`/api/admin/workshops/${id}`, { method: "DELETE" }),
};

export const usersApi = {
  list: () => proxyFetch<OrgUser[]>("/api/admin/users"),
  create: (payload: OrgUserCreate) =>
    proxyFetch<OrgUser>("/api/admin/users", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: OrgUserUpdate) =>
    proxyFetch<OrgUser>(`/api/admin/users/${id}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  remove: (id: string) => proxyFetch<void>(`/api/admin/users/${id}`, { method: "DELETE" }),
};

export const slesarkaStatusesApi = {
  list: () => proxyFetch<SlesarkaStatus[]>("/api/admin/slesarka-statuses"),
  create: (name: string, color: string) =>
    proxyFetch<SlesarkaStatus>("/api/admin/slesarka-statuses", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name, color }),
    }),
  update: (id: string, name: string, color: string) =>
    proxyFetch<SlesarkaStatus>(`/api/admin/slesarka-statuses/${id}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify({ name, color }),
    }),
  remove: (id: string) => proxyFetch<void>(`/api/admin/slesarka-statuses/${id}`, { method: "DELETE" }),
};

export const auditLogApi = {
  list: () => proxyFetch<AuditLogEntry[]>("/api/admin/audit-log"),
};
